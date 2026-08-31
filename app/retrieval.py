import asyncio
import json
import math
import re
import threading
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from pydantic import ConfigDict, Field

from app.chroma_collections import project_collection_name, verify_project_collection
from app.retry import with_transient_retry
from app.retrieval_errors import classify_retrieval_failure
from app.lexical_tokens import tokens as lexical_tokens
from app.retrieval_pipeline import BM25Retriever
from app.table_evidence import normalize_table_dialect
from app.telemetry import retrieval_discarded, retrieval_failure, retrieval_fallback
from app.vocabulary import CorpusVocabulary, VOCABULARY_RECORD_KIND


@dataclass(frozen=True, slots=True)
class _FallbackCorpus:
    expires_at: float
    documents: tuple[Document, ...]
    truncated: bool
    document_frequency: dict[str, int]
    term_frequencies: tuple[dict[str, int], ...]
    document_lengths: tuple[int, ...]
    average_document_length: float


_FALLBACK_CORPUS_CACHE: dict[tuple[object, ...], _FallbackCorpus] = {}
_FALLBACK_CORPUS_LOCK = threading.Lock()
_CHROMA_CLIENTS: dict[tuple[str, int], Any] = {}
_CHROMA_COLLECTIONS: dict[tuple[str, int, str], Any] = {}
_CHROMA_CLIENTS_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class _CachedVocabulary:
    expires_at: float
    value: CorpusVocabulary


_VOCABULARY_CACHE: dict[tuple[str, str], _CachedVocabulary] = {}
_VOCABULARY_CACHE_LOCK = threading.Lock()


async def warm_authorized_lexical_corpora(settings: Any, embedder: Any) -> int:
    """Build each project-scoped BM25 corpus before readiness succeeds."""

    from chromadb import HttpClient

    client = HttpClient(host=settings.chroma_host, port=settings.chroma_port)
    warmed = 0
    for collection in await asyncio.to_thread(client.list_collections):
        metadata = getattr(collection, "metadata", None) or {}
        project_id = str(metadata.get("project_id") or "").strip()
        if (
            not project_id
            or metadata.get("logical_collection") != settings.chroma_collection
        ):
            continue
        retriever = ChromaAccessRetriever.create(
            chroma_host=settings.chroma_host,
            chroma_port=settings.chroma_port,
            collection_name=settings.chroma_collection,
            text_field="chunk_text",
            project_id=project_id,
            access_policy_ids=(f"project:{project_id}",),
            top_k=settings.retrieval_top_k,
            score_threshold=settings.retrieval_score_threshold,
            required_schema_version=settings.supported_schema_versions[0],
            required_embedding_model=settings.supported_embedding_models[0],
            retry_attempts=settings.dependency_retry_attempts,
            timeout_seconds=settings.dependency_timeout_seconds,
            lexical_fallback_enabled=settings.lexical_fallback_enabled,
            lexical_fallback_max_records=settings.lexical_fallback_max_records,
            lexical_fallback_cache_ttl_seconds=settings.lexical_fallback_cache_ttl_seconds,
            vocabulary_cache_ttl_seconds=settings.vocabulary_cache_ttl_seconds,
            embedder=embedder,
        )
        # These are the exact scopes produced by query planning. CODE_ASSISTED
        # and CROSS_SOURCE split PAGE/CODE into independent calls, while delivery
        # uses ISSUE and the remaining intents use the mixed corpus.
        for source_scope in ((), ("PAGE",), ("CODE",), ("ISSUE",)):
            await asyncio.to_thread(
                retriever._cached_authorized_corpus, source_scope
            )
        warmed += 1
    return warmed


class ChromaAccessRetriever(BaseRetriever):
    """LangChain retriever that cannot execute without authorization filters."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    index: Any
    chroma_host: str = ""
    collection_name: str
    text_field: str = "chunk_text"
    embedder: Any = None
    project_id: str
    access_policy_ids: tuple[str, ...]
    required_schema_version: str = ""
    required_embedding_model: str = ""
    top_k: int = Field(default=8, ge=1, le=50)
    score_threshold: float = Field(default=0.25, ge=0, le=1)
    retry_attempts: int = Field(default=3, ge=1, le=5)
    timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    lexical_fallback_enabled: bool = True
    lexical_fallback_max_records: int = Field(default=5000, ge=100, le=20_000)
    lexical_fallback_cache_ttl_seconds: int = Field(default=300, ge=0, le=3600)
    vocabulary_cache_ttl_seconds: int = Field(default=300, ge=0, le=3600)
    _usage_events: list[dict[str, int]] = []
    _usage_lock: Any = None
    _retry_total: int = 0

    @classmethod
    def create(
        cls,
        *,
        chroma_host: str,
        chroma_port: int,
        collection_name: str,
        text_field: str,
        project_id: str,
        access_policy_ids: tuple[str, ...],
        top_k: int,
        score_threshold: float,
        required_schema_version: str = "",
        required_embedding_model: str = "",
        retry_attempts: int = 3,
        timeout_seconds: float = 20.0,
        lexical_fallback_enabled: bool = True,
        lexical_fallback_max_records: int = 5000,
        lexical_fallback_cache_ttl_seconds: int = 300,
        vocabulary_cache_ttl_seconds: int = 300,
        embedder: Any = None,
    ) -> "ChromaAccessRetriever":
        normalized_host = chroma_host.lower().rstrip(".")
        if not normalized_host or chroma_port < 1 or not collection_name:
            raise ValueError("Chroma is not configured.")
        if not access_policy_ids or f"project:{project_id}" not in access_policy_ids:
            raise ValueError("Authorized project policy is required.")
        if embedder is None:
            raise ValueError("The local query embedder is required.")
        physical_name = project_collection_name(collection_name, project_id)
        key = (normalized_host, chroma_port)
        collection_key = (*key, physical_name)
        with _CHROMA_CLIENTS_LOCK:
            collection = _CHROMA_COLLECTIONS.get(collection_key)
            if collection is None:
                from chromadb import HttpClient

                client = _CHROMA_CLIENTS.get(key)
                if client is None:
                    client = HttpClient(host=chroma_host, port=chroma_port)
                    _CHROMA_CLIENTS[key] = client
                collection = client.get_collection(physical_name)
                _CHROMA_COLLECTIONS[collection_key] = collection
        verify_project_collection(collection, collection_name, project_id)
        return cls(
            index=collection,
            chroma_host=normalized_host,
            collection_name=physical_name,
            text_field=text_field,
            embedder=embedder,
            project_id=project_id,
            access_policy_ids=access_policy_ids,
            required_schema_version=required_schema_version,
            required_embedding_model=required_embedding_model,
            top_k=top_k,
            score_threshold=score_threshold,
            retry_attempts=retry_attempts,
            timeout_seconds=timeout_seconds,
            lexical_fallback_enabled=lexical_fallback_enabled,
            lexical_fallback_max_records=lexical_fallback_max_records,
            lexical_fallback_cache_ttl_seconds=lexical_fallback_cache_ttl_seconds,
            vocabulary_cache_ttl_seconds=vocabulary_cache_ttl_seconds,
        )

    def model_post_init(self, __context: Any) -> None:
        self._usage_events = []
        self._usage_lock = threading.Lock()
        self._retry_total = 0

    def _get_relevant_documents(self, query: str, *, run_manager=None) -> list[Document]:
        return self._search(query, ())

    def _search(self, query: str, source_types: tuple[str, ...]) -> list[Document]:
        filters: list[dict[str, dict[str, str | list[str]]]] = [
            {"project_id": {"$eq": self.project_id}},
            {"access_policy_id": {"$eq": f"project:{self.project_id}"}},
            # The vocabulary record is control metadata, not evidence. Filtering
            # by its reserved canonical id preserves compatibility with existing
            # chunks that predate the record_kind field while ensuring it cannot
            # consume one of the finite dense-retrieval slots.
            {"canonical_chunk_id": {"$ne": VOCABULARY_RECORD_KIND}},
        ]
        normalized_types = tuple(
            dict.fromkeys(value.strip().upper() for value in source_types if value.strip())
        )
        if normalized_types:
            filters.append(
                {"source_type": {"$eq": normalized_types[0]}}
                if len(normalized_types) == 1
                else {"source_type": {"$in": list(normalized_types)}}
            )
        metadata_filter = {"$and": filters}
        fields = [
                self.text_field,
                "source_type",
                "title",
                "reference",
                "source_url",
                "provider",
                "source_id",
                "language",
                "locator",
                "schema_version",
                "source_version",
                "visual_eligible",
                "visual_types",
                "visual_asset_ids",
                "visual_asset_types",
                "visual_asset_captions",
                "page_number",
                "captions",
                "project_id",
                "access_policy_id",
                "embedding_model",
                "chunk_ordinal",
                "parent_id",
                "content_hash",
                "structure_path",
                "structure_root",
                "structure_leaf",
                "repository",
                "branch",
                "path",
                "file_name",
                "blob_sha",
                "commit_sha",
                "symbol",
                "symbols",
                "important_kwd",
                "project_key",
                "chunk_kind",
                "chunk_char_count",
                "chunk_token_count",
                "issue_key",
                "issue_type",
                "status",
                "priority",
                "assignee",
                "reporter",
                "due_date",
                "labels",
                "security_classification",
                "credential_sensitive",
            ]
        hits = self._search_local_vector(query, metadata_filter)
        documents: list[Document] = []
        drops: dict[str, int] = {}
        for chunk_id, score, hit_fields in hits:
            document = self._document_from_fields(hit_fields, chunk_id, score, drops)
            if document is not None:
                documents.append(document)
        # A collection whose records carry a different schema version or embedding
        # model matches the metadata filter and is then dropped here, chunk by
        # chunk, leaving no evidence and no explanation. Naming the discarded
        # majority turns that into a diagnosis instead of an empty answer.
        if hits and not documents:
            retrieval_discarded(
                project_id=self.project_id,
                collection_name=self.collection_name,
                matched=len(hits),
                reasons=drops,
                source_scope=",".join(normalized_types) or "MIXED",
            )
        return documents

    def _search_local_vector(
        self, query: str, metadata_filter: dict[str, object]
    ) -> list[tuple[str, float, dict[str, object]]]:
        """Query with a locally computed vector so no provider embedding quota is spent."""

        vector = self.embedder.embed_query(query)
        response = self.index.query(query_embeddings=[vector], n_results=self.top_k, where=metadata_filter, include=["documents", "metadatas", "distances"])
        self._record_usage(None, embedded_locally=True)
        hits: list[tuple[str, float, dict[str, object]]] = []
        for chunk_id, text, metadata, distance in zip(response.get("ids", [[]])[0], response.get("documents", [[]])[0], response.get("metadatas", [[]])[0], response.get("distances", [[]])[0], strict=True):
            fields = dict(metadata or {})
            fields[self.text_field] = text or ""
            hits.append((str(chunk_id), max(0.0, 1.0 - float(distance or 0.0)), fields))
        return hits

    def _record_usage(self, usage: object, *, embedded_locally: bool) -> None:
        if not isinstance(usage, dict):
            return
        with self._usage_lock:
            self._usage_events.append(
                {
                    "embedding_tokens": 0
                    if embedded_locally
                    else int(usage.get("embed_total_tokens") or 0),
                    "read_units": int(usage.get("read_units") or 0),
                }
            )

    def _document_from_fields(
        self, fields: dict[str, object], chunk_id: str, score: float,
        drops: dict[str, int] | None = None,
    ) -> Document | None:
        def drop(reason: str) -> None:
            if drops is not None:
                drops[reason] = drops.get(reason, 0) + 1

        if fields.get("record_kind") == VOCABULARY_RECORD_KIND:
            drop("reserved_record")
            return None
        text = str(fields.get(self.text_field) or "")
        # The separatorless dialect is emitted by Confluence PAGE ingestion.
        # Applying the adapter to executable source would misread consecutive
        # boolean-or expressions as table rows because raw code chunks are not
        # necessarily fenced. Documents already arrive as canonical Markdown.
        if str(fields.get("source_type") or "DOCUMENT").upper() == "PAGE":
            text = normalize_table_dialect(text)
        if score and score < self.score_threshold:
            drop("below_score_threshold")
            return None
        if not text:
            drop("empty_text_field")
            return None
        required_policy = f"project:{self.project_id}"
        strict = bool(self.required_schema_version or self.required_embedding_model)
        project_value = fields.get("project_id")
        policy_value = fields.get("access_policy_id")
        if strict and (project_value != self.project_id or policy_value != required_policy):
            drop("project_or_policy_mismatch")
            return None
        if not strict and project_value not in (None, "", self.project_id):
            drop("project_or_policy_mismatch")
            return None
        if not strict and policy_value not in (None, "", required_policy):
            drop("project_or_policy_mismatch")
            return None
        found_schema = str(fields.get("schema_version") or "")
        if self.required_schema_version and found_schema != self.required_schema_version:
            drop(f"schema_version:expected={self.required_schema_version},found={found_schema or 'absent'}")
            return None
        found_model = str(fields.get("embedding_model") or "")
        if self.required_embedding_model and found_model != self.required_embedding_model:
            drop(f"embedding_model:expected={self.required_embedding_model},found={found_model or 'absent'}")
            return None
        return Document(
            page_content=text,
            metadata={
                "score": score,
                "project_id": str(fields.get("project_id") or ""),
                "access_policy_id": str(fields.get("access_policy_id") or ""),
                "source_type": str(fields.get("source_type") or "DOCUMENT"),
                "title": str(fields.get("title") or "Untitled source"),
                "reference": str(fields.get("reference") or ""),
                "source_url": str(fields.get("source_url") or ""),
                "provider": str(fields.get("provider") or ""),
                "source_id": str(fields.get("source_id") or ""),
                "language": str(fields.get("language") or "und"),
                "locator": str(fields.get("locator") or ""),
                "schema_version": str(fields.get("schema_version") or ""),
                "source_version": str(fields.get("source_version") or ""),
                "embedding_model": str(fields.get("embedding_model") or ""),
                "visual_eligible": bool(fields.get("visual_eligible", False)),
                "visual_types": _list_field(fields.get("visual_types")),
                "visual_asset_ids": _list_field(fields.get("visual_asset_ids")),
                "visual_asset_types": _list_field(fields.get("visual_asset_types")),
                "visual_asset_captions": _list_field(fields.get("visual_asset_captions")),
                "page_number": int(fields.get("page_number") or 0) or None,
                "caption": " ".join(str(value) for value in _list_field(fields.get("captions"))),
                "chunk_id": str(fields.get("canonical_chunk_id") or chunk_id),
                "chunk_ordinal": int(fields.get("chunk_ordinal") or 0),
                "parent_id": str(fields.get("parent_id") or fields.get("source_id") or ""),
                "content_hash": str(fields.get("content_hash") or ""),
                "structure_path": _list_field(fields.get("structure_path")),
                "structure_root": str(fields.get("structure_root") or ""),
                "structure_leaf": str(fields.get("structure_leaf") or ""),
                "repository": str(fields.get("repository") or ""),
                "branch": str(fields.get("branch") or ""),
                "path": str(fields.get("path") or ""),
                "file_name": str(fields.get("file_name") or ""),
                "blob_sha": str(fields.get("blob_sha") or ""),
                "commit_sha": str(fields.get("commit_sha") or ""),
                "symbol": str(fields.get("symbol") or ""),
                "symbols": _list_field(fields.get("symbols")),
                "important_kwd": _list_field(fields.get("important_kwd")),
                "project_key": str(fields.get("project_key") or ""),
                "chunk_kind": str(fields.get("chunk_kind") or ""),
                "chunk_char_count": int(fields.get("chunk_char_count") or 0),
                "chunk_token_count": int(fields.get("chunk_token_count") or 0),
                "issue_key": str(fields.get("issue_key") or ""),
                "issue_type": str(fields.get("issue_type") or ""),
                "status": str(fields.get("status") or ""),
                "priority": str(fields.get("priority") or ""),
                "assignee": str(fields.get("assignee") or ""),
                "reporter": str(fields.get("reporter") or ""),
                "due_date": str(fields.get("due_date") or ""),
                "labels": _list_field(fields.get("labels")),
                "security_classification": str(fields.get("security_classification") or ""),
                "credential_sensitive": bool(fields.get("credential_sensitive", False)),
                "doc_category": str(fields.get("doc_category") or "narrative"),
                "category_reason": str(fields.get("category_reason") or ""),
                "category_warning": str(fields.get("category_warning") or ""),
                "identifiers": _list_field(fields.get("identifiers")),
                "entity": str(fields.get("entity") or "").casefold(),
                "entity_key": str(fields.get("entity_key") or ""),
                "record_kind": str(fields.get("record_kind") or ""),
            },
        )

    def corpus_vocabulary(self) -> CorpusVocabulary:
        """Load the reserved project record without admitting it as evidence."""

        key = (self.collection_name, self.project_id)
        now = time.monotonic()
        with _VOCABULARY_CACHE_LOCK:
            cached = _VOCABULARY_CACHE.get(key)
            if cached is not None and cached.expires_at > now:
                return cached.value
        try:
            response = self.index.get(
                where={
                    "$and": [
                        {"project_id": {"$eq": self.project_id}},
                        {
                            "access_policy_id": {
                                "$eq": f"project:{self.project_id}"
                            }
                        },
                        {"record_kind": {"$eq": VOCABULARY_RECORD_KIND}},
                    ]
                },
                limit=1,
                include=["documents", "metadatas"],
            )
            documents = response.get("documents", [])
            metadatas = response.get("metadatas", [])
            vocabulary = CorpusVocabulary.from_record(
                dict(metadatas[0] or {}) if metadatas else {},
                str(documents[0] or "") if documents else "",
            )
        except Exception:
            vocabulary = CorpusVocabulary()
        expires_at = now + self.vocabulary_cache_ttl_seconds
        with _VOCABULARY_CACHE_LOCK:
            _VOCABULARY_CACHE[key] = _CachedVocabulary(expires_at, vocabulary)
        return vocabulary

    async def _aget_relevant_documents(
        self, query: str, *, run_manager=None
    ) -> list[Document]:
        return await self.ainvoke_scoped(query)

    async def ainvoke_scoped(
        self, query: str, source_types: tuple[str, ...] = ()
    ) -> list[Document]:
        """Retrieve with an additional server-selected source boundary."""

        try:
            documents, retry_count = await with_transient_retry(
                lambda: asyncio.to_thread(self._search, query, source_types),
                attempts=self.retry_attempts,
                timeout_seconds=self.timeout_seconds,
            )
        except Exception as error:
            failure = classify_retrieval_failure(error)
            retrieval_failure(
                project_id=self.project_id,
                provider="chroma",
                failure_code=failure.code,
                status_code=failure.status_code,
                retryable=failure.retryable,
                configured_attempts=self.retry_attempts,
                model_name=self.required_embedding_model or "unknown",
                source_scope=",".join(source_types) or "MIXED",
            )
            if (
                self.lexical_fallback_enabled
            ):
                documents = await asyncio.to_thread(
                    self._lexical_fallback, query, source_types, failure.code
                )
                retry_count = 0
            else:
                raise
        with self._usage_lock:
            self._retry_total += retry_count
        for document in documents:
            document.metadata["retrieval_retry_count"] = retry_count
        return documents

    async def ainvoke_exact_identifiers(
        self, identifiers: tuple[str, ...], source_types: tuple[str, ...] = ()
    ) -> list[Document]:
        return await asyncio.to_thread(
            self._exact_identifier_documents, identifiers, source_types
        )

    async def ainvoke_lexical(
        self, query: str, source_types: tuple[str, ...] = ()
    ) -> list[Document]:
        return await asyncio.to_thread(self._lexical_candidates, query, source_types)

    async def ainvoke_rare_terms(
        self, query: str, source_types: tuple[str, ...] = ()
    ) -> tuple[str, ...]:
        """Return bottom-decile query terms from the authorized corpus."""

        return await asyncio.to_thread(self._rare_query_terms, query, source_types)

    async def ainvoke_source_siblings(
        self, source_ids: tuple[str, ...], source_types: tuple[str, ...] = ()
    ) -> list[Document]:
        """Load remaining authorized chunks for already-retrieved sources."""

        normalized_ids = tuple(
            dict.fromkeys(value.strip() for value in source_ids if value.strip())
        )
        if not normalized_ids:
            return []
        return await asyncio.to_thread(
            self._source_sibling_documents, normalized_ids, source_types
        )

    async def ainvoke_population(
        self,
        entity: str = "",
        labels: tuple[str, ...] = (),
        source_types: tuple[str, ...] = (),
    ) -> list[Document]:
        """Load the authorized registry population for an exhaustive question."""

        return await asyncio.to_thread(
            self._population_documents, entity, labels, source_types
        )

    def _source_sibling_documents(
        self, source_ids: tuple[str, ...], source_types: tuple[str, ...]
    ) -> list[Document]:
        filters: list[dict[str, object]] = [
            {"project_id": {"$eq": self.project_id}},
            {"access_policy_id": {"$eq": f"project:{self.project_id}"}},
            {"canonical_chunk_id": {"$ne": VOCABULARY_RECORD_KIND}},
            {"source_id": {"$in": list(source_ids)}},
        ]
        normalized_types = tuple(
            dict.fromkeys(value.strip().upper() for value in source_types if value.strip())
        )
        if normalized_types:
            filters.append(
                {"source_type": {"$eq": normalized_types[0]}}
                if len(normalized_types) == 1
                else {"source_type": {"$in": list(normalized_types)}}
            )
        maximum_records = min(
            self.lexical_fallback_max_records,
            self.top_k * self.top_k,
        )
        response = self.index.get(
            where={"$and": filters},
            limit=maximum_records,
            include=["documents", "metadatas"],
        )
        documents: list[Document] = []
        drops: dict[str, int] = {}
        for chunk_id, text, metadata in zip(
            response.get("ids", []),
            response.get("documents", []),
            response.get("metadatas", []),
            strict=True,
        ):
            fields = dict(metadata or {})
            fields[self.text_field] = text or ""
            document = self._document_from_fields(fields, str(chunk_id), 1.0, drops)
            if document is None:
                continue
            document.metadata["retrieval_channel"] = "authorized_source_sibling"
            documents.append(document)
        return sorted(
            documents,
            key=lambda document: (
                str(document.metadata.get("source_id") or ""),
                int(document.metadata.get("chunk_ordinal") or 0),
            ),
        )

    def _exact_identifier_documents(
        self, identifiers: tuple[str, ...], source_types: tuple[str, ...]
    ) -> list[Document]:
        filters: list[dict[str, object]] = [
            {"project_id": {"$eq": self.project_id}},
            {"access_policy_id": {"$eq": f"project:{self.project_id}"}},
            {"canonical_chunk_id": {"$ne": VOCABULARY_RECORD_KIND}},
        ]
        normalized_types = tuple(
            dict.fromkeys(value.strip().upper() for value in source_types if value.strip())
        )
        if normalized_types:
            filters.append(
                {"source_type": {"$eq": normalized_types[0]}}
                if len(normalized_types) == 1
                else {"source_type": {"$in": list(normalized_types)}}
            )
        if not identifiers:
            return []
        where_document: dict[str, object] = (
            {"$contains": identifiers[0]}
            if len(identifiers) == 1
            else {"$or": [{"$contains": identifier} for identifier in identifiers]}
        )
        response = self.index.get(
            where={"$and": filters},
            where_document=where_document,
            include=["documents", "metadatas"],
        )
        found: dict[str, Document] = {}
        drops: dict[str, int] = {}
        for chunk_id, text, metadata in zip(
            response.get("ids", []), response.get("documents", []),
            response.get("metadatas", []), strict=True,
        ):
            fields = dict(metadata or {})
            fields[self.text_field] = text or ""
            document = self._document_from_fields(fields, str(chunk_id), 1.0, drops)
            if document is None:
                continue
            document.metadata["identifier_anchor"] = True
            document.metadata["identifier_anchor_score"] = max(
                _identifier_anchor_score(identifier, document)
                for identifier in identifiers
            )
            found[str(document.metadata.get("chunk_id") or chunk_id)] = document
        return sorted(
            found.values(),
            key=lambda item: float(item.metadata.get("identifier_anchor_score") or 0),
            reverse=True,
        )[:12]

    def _lexical_fallback(
        self, query: str, source_types: tuple[str, ...], failure_code: str
    ) -> list[Document]:
        cached = self._cached_authorized_corpus(source_types)
        ranked = _rank_cached_corpus(query, cached)
        for document in ranked:
            document.metadata["retrieval_channel"] = "lexical_fallback"
            document.metadata["retrieval_fallback"] = True
        retrieval_fallback(
            project_id=self.project_id,
            provider="chroma",
            failure_code=failure_code,
            record_count=len(cached.documents),
            truncated=cached.truncated,
            source_scope=",".join(source_types) or "MIXED",
        )
        return ranked[: self.top_k]

    def _lexical_candidates(
        self, query: str, source_types: tuple[str, ...]
    ) -> list[Document]:
        cached = self._cached_authorized_corpus(source_types)
        ranked = _rank_cached_corpus(query, cached)
        for document in ranked:
            document.metadata["retrieval_channel"] = "lexical"
        return ranked[: self.top_k]

    def _rare_query_terms(
        self, query: str, source_types: tuple[str, ...]
    ) -> tuple[str, ...]:
        cached = self._cached_authorized_corpus(source_types)
        corpus = cached.documents
        if not corpus:
            return ()
        query_terms = tuple(
            dict.fromkeys(
                term
                for term in lexical_tokens(query)
                if len(term) >= 2 and not term.isdigit()
            )
        )
        frequencies = {
            term: int(cached.document_frequency.get(term, 0))
            for term in query_terms
        }
        # "Bottom decile" is a corpus property, not the least-common word in
        # each individual question. Computing the percentile over query terms
        # caused an ordinary word to be labelled rare on nearly every request,
        # triggering broad `$contains` scans and noisy identifier anchors.
        observed = sorted(
            value for value in cached.document_frequency.values() if value > 0
        )
        if not observed:
            return ()
        decile_index = min(len(observed) - 1, max(0, (len(observed) - 1) // 10))
        threshold = observed[decile_index]
        return tuple(
            term
            for term in query_terms
            if 0 < frequencies[term] <= threshold
        )[:5]

    def _population_documents(
        self,
        entity: str,
        labels: tuple[str, ...],
        source_types: tuple[str, ...],
    ) -> list[Document]:
        normalized_entity = entity.strip().casefold()
        normalized_labels = tuple(
            value.strip().casefold() for value in labels if value.strip()
        )
        population: dict[str, Document] = {}
        for cached in self._cached_authorized_corpus(source_types).documents:
            document = _clone_document(cached)
            metadata = document.metadata
            if str(metadata.get("doc_category") or "").casefold() not in {
                "entity-contract",
                "registry-table",
            }:
                continue
            if normalized_entity and str(metadata.get("entity") or "").casefold() not in {
                "",
                normalized_entity,
            }:
                continue
            searchable = " ".join(
                (
                    document.page_content,
                    str(metadata.get("title") or ""),
                    " ".join(
                        str(value) for value in metadata.get("structure_path", [])
                    ),
                )
            ).casefold()
            if normalized_labels and not any(
                label in searchable for label in normalized_labels
            ):
                continue
            entity_key = str(metadata.get("entity_key") or "").strip()
            if entity_key:
                population.setdefault(entity_key, document)
        return [population[key] for key in sorted(population)]

    def _cached_authorized_corpus(
        self, source_types: tuple[str, ...]
    ) -> _FallbackCorpus:
        key = (
            self.chroma_host,
            self.collection_name,
            self.project_id,
            tuple(sorted(self.access_policy_ids)),
            tuple(sorted(source_types)),
        )
        now = time.monotonic()
        cached: _FallbackCorpus | None = None
        if self.lexical_fallback_cache_ttl_seconds:
            with _FALLBACK_CORPUS_LOCK:
                cached = _FALLBACK_CORPUS_CACHE.get(key)
            if cached and cached.expires_at <= now:
                cached = None
        if cached is None:
            documents, truncated = self._fetch_fallback_corpus(source_types)
            document_frequency, term_frequencies, document_lengths = _lexical_index(
                documents
            )
            cached = _FallbackCorpus(
                expires_at=now + self.lexical_fallback_cache_ttl_seconds,
                documents=tuple(documents),
                truncated=truncated,
                document_frequency=document_frequency,
                term_frequencies=term_frequencies,
                document_lengths=document_lengths,
                average_document_length=(
                    sum(document_lengths) / max(1, len(document_lengths))
                ),
            )
            if self.lexical_fallback_cache_ttl_seconds:
                with _FALLBACK_CORPUS_LOCK:
                    _FALLBACK_CORPUS_CACHE[key] = cached
        return cached

    def _fetch_fallback_corpus(
        self, source_types: tuple[str, ...]
    ) -> tuple[list[Document], bool]:
        base_filters: list[dict[str, object]] = [
            {"project_id": {"$eq": self.project_id}},
            {"access_policy_id": {"$eq": f"project:{self.project_id}"}},
            {"canonical_chunk_id": {"$ne": VOCABULARY_RECORD_KIND}},
        ]
        normalized_types = tuple(
            dict.fromkeys(
                value.strip().upper() for value in source_types if value.strip()
            )
        )
        # Chroma returns records in insertion order. A single bounded mixed-source
        # scan therefore sampled only CODE in the measured corpus (10,449 CODE
        # records precede 541 PAGE records), making the independent lexical
        # channel actively harmful for documentation questions. Fill the bounded
        # cache one source family at a time, with user-facing evidence first.
        priority = {"PAGE": 0, "ATTACHMENT": 1, "ISSUE": 2, "CODE": 3}
        source_partitions: tuple[str | None, ...]
        if len(normalized_types) == 1:
            source_partitions = (normalized_types[0],)
        else:
            requested = normalized_types or tuple(priority)
            source_partitions = tuple(
                sorted(requested, key=lambda value: (priority.get(value, 99), value))
            )
        records: list[Document] = []
        truncated = False
        for source_type in source_partitions:
            filters = list(base_filters)
            if source_type is not None:
                filters.append({"source_type": {"$eq": source_type}})
            offset = 0
            while len(records) < self.lexical_fallback_max_records:
                response = self.index.get(
                    where={"$and": filters},
                    limit=min(
                        100, self.lexical_fallback_max_records - len(records)
                    ),
                    offset=offset,
                    include=["documents", "metadatas"],
                )
                ids = response.get("ids", [])
                for chunk_id, text, metadata in zip(
                    ids,
                    response.get("documents", []),
                    response.get("metadatas", []),
                    strict=True,
                ):
                    fields = dict(metadata or {})
                    fields[self.text_field] = text or ""
                    document = self._document_from_fields(
                        fields, str(chunk_id), 0.0
                    )
                    if document is not None:
                        records.append(document)
                offset += len(ids)
                if len(ids) < 100:
                    break
            if len(records) >= self.lexical_fallback_max_records:
                truncated = True
                break
        if len(records) >= self.lexical_fallback_max_records:
            truncated = True
        return records, truncated
    def drain_usage(self) -> dict[str, int]:
        with self._usage_lock:
            events = self._usage_events
            self._usage_events = []
            retry_count = self._retry_total
            self._retry_total = 0
        return {
            "embedding_tokens": sum(event["embedding_tokens"] for event in events),
            "read_units": sum(event["read_units"] for event in events),
            "retry_count": retry_count,
        }


def _clone_document(document: Document) -> Document:
    """Copy cached evidence before BM25 adds request-local ranking metadata."""

    return Document(page_content=document.page_content, metadata=dict(document.metadata))


def _lexical_index(
    documents: list[Document],
) -> tuple[dict[str, int], tuple[dict[str, int], ...], tuple[int, ...]]:
    document_frequency: dict[str, int] = {}
    term_frequencies: list[dict[str, int]] = []
    lengths: list[int] = []
    for document in documents:
        searchable = document.page_content + " " + BM25Retriever._metadata(document)
        terms = lexical_tokens(searchable)
        counts: dict[str, int] = {}
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
        for term in counts:
            document_frequency[term] = document_frequency.get(term, 0) + 1
        term_frequencies.append(counts)
        lengths.append(len(terms))
    return document_frequency, tuple(term_frequencies), tuple(lengths)


def _rank_cached_corpus(query: str, cached: _FallbackCorpus) -> list[Document]:
    query_terms = set(lexical_tokens(query))
    document_count = len(cached.documents)
    scored: list[tuple[float, int, Document]] = []
    k1, b = 1.2, 0.75
    for index, (document, frequencies, length) in enumerate(
        zip(
            cached.documents,
            cached.term_frequencies,
            cached.document_lengths,
            strict=True,
        )
    ):
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            df = cached.document_frequency.get(term, 0)
            idf = math.log(1 + (document_count - df + 0.5) / (df + 0.5))
            length_norm = 1 - b + b * length / max(cached.average_document_length, 1)
            score += idf * (frequency * (k1 + 1)) / (
                frequency + k1 * length_norm
            )
        clone = _clone_document(document)
        clone.metadata["lexical_score"] = score
        scored.append((score, -index, clone))
    ranked = [
        document
        for _score, _index, document in sorted(
            scored, key=lambda item: (item[0], item[1]), reverse=True
        )
    ]
    maximum_lexical_score = max(
        (float(document.metadata.get("lexical_score") or 0.0) for document in ranked),
        default=0.0,
    )
    for document in ranked:
        raw_score = float(document.metadata.get("lexical_score") or 0.0)
        document.metadata["score"] = (
            raw_score / maximum_lexical_score if maximum_lexical_score > 0 else 0.0
        )
    return ranked


def _identifier_anchor_score(identifier: str, document: Document) -> float:
    body = document.page_content
    title = str(document.metadata.get("title") or "")
    score = float(body.upper().count(identifier.upper()))
    if re.search(rf"@SerialName\(['\"]{re.escape(identifier)}['\"]\)", body):
        score += 100
    if "data class " in body and identifier.upper() in body.upper():
        score += 80
    if "Constant | Wire name | Id | Ver" in body or "wire name" in body.casefold():
        score += 60
    if "EventType" in title:
        score += 50
    if "Event and Integration Contract" in title:
        score += 40
    return score


def _list_field(value: object) -> list[object]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str) and value:
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return [value]
        return decoded if isinstance(decoded, list) else [decoded]
    return []
