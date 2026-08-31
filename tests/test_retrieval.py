import asyncio
from langchain_core.documents import Document

from app.retrieval import (
    ChromaAccessRetriever,
    _FallbackCorpus,
    _lexical_index,
    _rank_cached_corpus,
    warm_authorized_lexical_corpora,
)
from app.retrieval_errors import classify_retrieval_failure
from app.retrieval_pipeline import BM25Retriever
from app.table_evidence import contains_table
from app.vocabulary import VOCABULARY_RECORD_KIND


class QuotaFallbackIndex:
    def __init__(self) -> None:
        self.query_calls = 0
        self.get_calls = 0

    def query(self, **kwargs):
        self.query_calls += 1
        return _query_result("dense-1", "Dense result")

    def get(self, **kwargs):
        self.get_calls += 1
        return {
            "ids": ["fallback-1", "fallback-2"],
            "documents": [
                "POS home screen is implemented by HomeScreen.kt.",
                "Unrelated printer configuration.",
            ],
            "metadatas": [
                    {
                        "project_id": "DEMO",
                        "access_policy_id": "project:DEMO",
                        "schema_version": "3",
                        "embedding_model": "multilingual-e5-large",
                        "source_type": "CODE",
                        "title": "HomeScreen.kt",
                        "path": "src/HomeScreen.kt",
                        "file_name": "HomeScreen.kt",
                    }, {
                        "project_id": "DEMO",
                        "access_policy_id": "project:DEMO",
                        "schema_version": "3",
                        "embedding_model": "multilingual-e5-large",
                        "source_type": "CODE",
                        "title": "Printer.kt",
                    },
            ],
        }


class FakeEmbedder:
    def embed_query(self, query):
        return [0.1, 0.2]


class FailingEmbedder:
    def embed_query(self, query):
        error = RuntimeError("local embedding process temporarily unavailable")
        error.status_code = 503  # type: ignore[attr-defined]
        raise error


def _query_result(chunk_id="chunk-1", text="Only authorized project evidence."):
    return {
        "ids": [[chunk_id]],
        "documents": [[text]],
        "distances": [[0.09]],
        "metadatas": [[{
            "project_id": "DEMO",
            "access_policy_id": "project:DEMO",
            "schema_version": "3",
            "embedding_model": "multilingual-e5-large",
            "source_type": "CODE",
            "title": "Payment.kt",
            "reference": "repo:Payment.kt:1-4",
            "source_url": "https://github.example/Payment.kt",
        }]],
    }


class FakeIndex:
    def __init__(self) -> None:
        self.query_args = None

    def query(self, **kwargs):
        self.query_args = kwargs
        return _query_result()


class VocabularyIndex(FakeIndex):
    def get(self, **kwargs):
        self.get_args = kwargs
        return {
            "ids": ["vocabulary"],
            "documents": [""],
            "metadatas": [
                {
                    "record_kind": VOCABULARY_RECORD_KIND,
                    "entities": '["retail","warehouse"]',
                    "code_extensions": '[".swift",".tf"]',
                }
            ],
        }


class SourcePartitionedIndex(FakeIndex):
    def __init__(self) -> None:
        super().__init__()
        self.source_calls = []

    def get(self, **kwargs):
        source_filter = kwargs["where"]["$and"][-1]
        source_type = source_filter["source_type"]["$eq"]
        self.source_calls.append(source_type)
        available = 60 if source_type == "PAGE" else 100
        offset = kwargs["offset"]
        count = min(kwargs["limit"], max(0, available - offset))
        return {
            "ids": [f"{source_type}-{offset + index}" for index in range(count)],
            "documents": [f"{source_type} evidence" for _index in range(count)],
            "metadatas": [
                {
                    "project_id": "DEMO",
                    "access_policy_id": "project:DEMO",
                    "source_type": source_type,
                }
                for _index in range(count)
            ],
        }


def test_langchain_retriever_always_applies_project_and_access_filters() -> None:
    index = FakeIndex()
    retriever = ChromaAccessRetriever(
        index=index,
        collection_name="project-intelligence",
        embedder=FakeEmbedder(),
        project_id="DEMO",
        access_policy_ids=("project:DEMO", "user:user-id"),
        top_k=8,
        score_threshold=0.25,
    )
    documents = asyncio.run(retriever.ainvoke("How does payment work?"))

    assert len(documents) == 1
    assert documents[0].page_content == "Only authorized project evidence."
    assert index.query_args["where"] == {
        "$and": [
            {"project_id": {"$eq": "DEMO"}},
            {
                "access_policy_id": {"$eq": "project:DEMO"}
            },
            {"canonical_chunk_id": {"$ne": VOCABULARY_RECORD_KIND}},
        ]
    }


def test_scoped_retrieval_adds_source_filter_without_weakening_authorization() -> None:
    index = FakeIndex()
    retriever = ChromaAccessRetriever(
        index=index,
        collection_name="project-intelligence",
        embedder=FakeEmbedder(),
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
        top_k=8,
        score_threshold=0.25,
    )

    asyncio.run(retriever.ainvoke_scoped("How is login implemented?", ("CODE",)))

    assert index.query_args["where"] == {
        "$and": [
            {"project_id": {"$eq": "DEMO"}},
            {"access_policy_id": {"$eq": "project:DEMO"}},
            {"canonical_chunk_id": {"$ne": VOCABULARY_RECORD_KIND}},
            {"source_type": {"$eq": "CODE"}},
        ]
    }


def test_retrieval_boundary_canonicalizes_separatorless_page_tables() -> None:
    retriever = ChromaAccessRetriever(
        index=FakeIndex(),
        collection_name="project-intelligence",
        embedder=FakeEmbedder(),
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
        top_k=8,
        score_threshold=0.25,
    )
    document = retriever._document_from_fields(
        {
            "chunk_text": "Key | Action | Condition\nF1 | Close sale | main screen",
            "project_id": "DEMO",
            "access_policy_id": "project:DEMO",
            "source_type": "PAGE",
        },
        "page-table",
        0.9,
    )

    assert document is not None
    assert document.page_content == (
        "| Key | Action | Condition |\n"
        "| --- | --- | --- |\n"
        "| F1 | Close sale | main screen |"
    )
    assert contains_table(document.page_content) is True


def test_retrieval_boundary_does_not_rewrite_unfenced_source_code() -> None:
    retriever = ChromaAccessRetriever(
        index=FakeIndex(),
        collection_name="project-intelligence",
        embedder=FakeEmbedder(),
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
    )
    source = "first || second\nthird || fourth"
    document = retriever._document_from_fields(
        {
            "chunk_text": source,
            "project_id": "DEMO",
            "access_policy_id": "project:DEMO",
            "source_type": "CODE",
        },
        "code-with-or",
        0.9,
    )

    assert document is not None
    assert document.page_content == source


def test_vocabulary_is_loaded_by_reserved_kind_and_never_becomes_evidence() -> None:
    index = VocabularyIndex()
    retriever = ChromaAccessRetriever(
        index=index,
        collection_name="vocabulary-test",
        embedder=FakeEmbedder(),
        project_id="sample-project",
        access_policy_ids=("project:sample-project",),
        top_k=8,
        score_threshold=0.25,
        vocabulary_cache_ttl_seconds=0,
    )

    vocabulary = retriever.corpus_vocabulary()

    assert vocabulary.entities == ("retail", "warehouse")
    assert vocabulary.code_extensions == (".swift", ".tf")
    assert index.get_args["where"] == {
        "$and": [
            {"project_id": {"$eq": "sample-project"}},
            {"access_policy_id": {"$eq": "project:sample-project"}},
            {"record_kind": {"$eq": VOCABULARY_RECORD_KIND}},
        ]
    }
    assert (
        retriever._document_from_fields(
            {
                "record_kind": VOCABULARY_RECORD_KIND,
                "chunk_text": "reserved configuration",
            },
            "vocabulary",
            1.0,
        )
        is None
    )


def test_monthly_embedding_quota_failure_is_classified_and_not_retryable() -> None:
    error = RuntimeError(
        "(429) RESOURCE_EXHAUSTED: reached the embedding token limit for the current month"
    )
    error.status_code = 429  # type: ignore[attr-defined]

    failure = classify_retrieval_failure(error)

    assert failure.code == "EMBEDDING_QUOTA_EXHAUSTED"
    assert failure.status_code == 429
    assert failure.retryable is False


def test_quota_failure_uses_authorized_bm25_fallback() -> None:
    index = QuotaFallbackIndex()
    retriever = ChromaAccessRetriever(
        index=index,
        chroma_host="localhost",
        collection_name="project-intelligence",
        embedder=FailingEmbedder(),
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
        required_schema_version="3",
        required_embedding_model="multilingual-e5-large",
        top_k=1,
        lexical_fallback_cache_ttl_seconds=300,
    )

    documents = asyncio.run(
        retriever.ainvoke_scoped("Which file implements the POS home screen?", ("CODE",))
    )

    assert [document.metadata["file_name"] for document in documents] == ["HomeScreen.kt"]
    assert documents[0].metadata["retrieval_channel"] == "lexical_fallback"
    assert documents[0].metadata["retrieval_fallback"] is True
    assert index.query_calls == 0
    assert index.get_calls == 1


def test_dense_retrieval_is_retried_on_the_next_request_after_fallback() -> None:
    class RecoveringEmbedder(FakeEmbedder):
        def __init__(self):
            self.calls = 0

        def embed_query(self, query):
            self.calls += 1
            if self.calls == 1:
                error = RuntimeError(
                    "local embedding process temporarily unavailable"
                )
                error.status_code = 503  # type: ignore[attr-defined]
                raise error
            return super().embed_query(query)

    index = QuotaFallbackIndex()
    embedder = RecoveringEmbedder()
    retriever = ChromaAccessRetriever(
        index=index,
        chroma_host="recovering.local",
        collection_name="project-intelligence",
        embedder=embedder,
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
        required_schema_version="3",
        required_embedding_model="multilingual-e5-large",
        retry_attempts=1,
        lexical_fallback_cache_ttl_seconds=300,
    )

    first = asyncio.run(retriever.ainvoke_scoped("home", ()))
    second = asyncio.run(retriever.ainvoke_scoped("home", ()))

    assert first[0].metadata["retrieval_fallback"] is True
    assert second[0].metadata.get("retrieval_fallback") is None
    assert embedder.calls == 2


def test_cached_lexical_index_matches_reference_bm25_order() -> None:
    documents = [
        Document(
            page_content="payment home screen",
            metadata={"chunk_id": "home", "title": "HomeScreen"},
        ),
        Document(
            page_content="printer configuration",
            metadata={"chunk_id": "printer", "title": "Printer"},
        ),
    ]
    document_frequency, term_frequencies, lengths = _lexical_index(documents)
    cached = _FallbackCorpus(
        expires_at=0,
        documents=tuple(documents),
        truncated=False,
        document_frequency=document_frequency,
        term_frequencies=term_frequencies,
        document_lengths=lengths,
        average_document_length=sum(lengths) / len(lengths),
    )

    reference = BM25Retriever().rank("payment screen", documents)
    optimized = _rank_cached_corpus("payment screen", cached)

    assert [item.metadata["chunk_id"] for item in optimized] == [
        item.metadata["chunk_id"] for item in reference
    ]
    assert [item.metadata["lexical_score"] for item in optimized] == [
        item.metadata["lexical_score"] for item in reference
    ]
    assert all(0.0 <= float(item.metadata["score"]) <= 1.0 for item in optimized)
    assert optimized[0].metadata["score"] == 1.0
    assert [item.metadata["chunk_id"] for item in optimized] == [
        item.metadata["chunk_id"]
        for item in sorted(
            optimized,
            key=lambda item: float(item.metadata["score"]),
            reverse=True,
        )
    ]


def test_mixed_lexical_corpus_reserves_space_for_page_evidence() -> None:
    index = SourcePartitionedIndex()
    retriever = ChromaAccessRetriever(
        index=index,
        collection_name="project-intelligence",
        embedder=FakeEmbedder(),
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
        lexical_fallback_max_records=100,
    )

    documents, truncated = retriever._fetch_fallback_corpus(("CODE", "PAGE"))

    assert truncated is True
    assert [document.metadata["source_type"] for document in documents[:60]] == [
        "PAGE"
    ] * 60
    assert [document.metadata["source_type"] for document in documents[60:]] == [
        "CODE"
    ] * 40
    assert index.source_calls[0] == "PAGE"


def test_rare_terms_use_corpus_percentile_not_query_percentile(monkeypatch) -> None:
    cached = _FallbackCorpus(
        expires_at=0,
        documents=(Document(page_content="common unicorn"),),
        truncated=False,
        document_frequency={
            "common": 100,
            "unicorn": 1,
            **{f"rare-{index}": 1 for index in range(9)},
        },
        term_frequencies=({},),
        document_lengths=(2,),
        average_document_length=2,
    )
    monkeypatch.setattr(
        ChromaAccessRetriever,
        "_cached_authorized_corpus",
        lambda _self, _source_types: cached,
    )

    assert _retriever_for_rare_terms()._rare_query_terms(
        "common unicorn", ()
    ) == ("unicorn",)


def _retriever_for_rare_terms() -> ChromaAccessRetriever:
    return ChromaAccessRetriever(
        index=FakeIndex(),
        collection_name="project-intelligence",
        embedder=FakeEmbedder(),
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
    )


def test_startup_warms_each_project_scoped_lexical_corpus(monkeypatch) -> None:
    class Collection:
        metadata = {
            "project_id": "DEMO",
            "logical_collection": "project-intelligence",
        }

    class Client:
        def list_collections(self):
            return [Collection()]

    warmed_scopes = []

    class Retriever:
        def _cached_authorized_corpus(self, scope):
            warmed_scopes.append(scope)

    import chromadb
    from app.config import Settings

    monkeypatch.setattr(chromadb, "HttpClient", lambda **_kwargs: Client())
    monkeypatch.setattr(
        ChromaAccessRetriever,
        "create",
        lambda **_kwargs: Retriever(),
    )
    count = asyncio.run(
        warm_authorized_lexical_corpora(
            Settings(_env_file=None, environment="development"), object()
        )
    )

    assert count == 1
    assert warmed_scopes == [(), ("PAGE",), ("CODE",), ("ISSUE",)]
