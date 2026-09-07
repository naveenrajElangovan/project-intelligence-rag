from __future__ import annotations

import asyncio
import hashlib
import math
import re
from collections import Counter

from langchain_core.documents import Document

from app.telemetry import stage_complete, started
from app.reranking import progressive_rerank_candidates
from app.workflow_nodes.state import RagState
from app.workflow_support.completeness import (
    _answer_requirements,
    _include_repair_evidence,
    _merge_ranked_documents,
    _missing_evidence_requirements,
)
from app.workflow_support.deterministic_answers import (
    _code_inventory_documents,
    _code_location_document_score,
)
from app.workflow_support.presentation import _expand_candidate_neighbors
from app.workflow_support.inventory_intent import is_inventory_question
from app.workflow_support.identifiers import member_identifiers
from app.workflow_support.procedural_retrieval import (
    balanced_source_candidate_pool,
    is_procedural_question,
    rerank_source_families,
)
from app.workflow_support.query_analysis import (
    _dedupe_source_documents,
    _document_source_type,
    _entity_overview_source_ids,
    _exact_feature_source_ids,
    _exact_term_ratio,
    _exact_terms,
    _implementation_evidence_order,
    _inventory_documents,
    _low_information_project_document,
    _project_overview_evidence_order,
    _required_evidence_source_types,
    _source_authority_valid,
    _source_diverse_order,
    _source_identity,
    _source_type_count,
)
from app.retrieval_pipeline import (
    BM25Retriever,
    HeuristicContextEvaluator,
    ReciprocalRankFusion,
    deduplicate_candidate_bodies,
    validate_authorized_candidates,
)
from app.source_policy import SourcePolicyRegistry, deduplicate_authoritative_versions


def _exact_identifier_tokens(
    value: str, entities: tuple[str, ...] = ()
) -> tuple[str, ...]:
    ignored = {"CODE", "API", "HTTP", "JSON", "SQL"} | {
        entity.upper() for entity in entities
    }
    identifiers = (
        identifier
        for identifier in member_identifiers(value)
        if identifier not in ignored
    )
    labels = re.findall(
        r"(?i)(?<![A-Za-z0-9])(?:\d+[a-z]{1,4}|v\d+(?:\.\d+)+)(?![A-Za-z0-9])",
        value,
    )
    quoted = (
        match.group(1).strip() if match.group(1) else match.group(2).strip()
        for match in re.finditer(r"`([^`]{2,80})`|[\"']([^\"']{2,80})[\"']", value)
    )
    return tuple(dict.fromkeys([*identifiers, *labels, *quoted]))


def _forced_anchor_tokens(value: str) -> tuple[str, ...]:
    """Return explicit labels/phrases that are safe to reserve as evidence."""

    labels = re.findall(
        r"(?i)(?<![A-Za-z0-9])(?:\d+[a-z]{1,4}|v\d+(?:\.\d+)+)(?![A-Za-z0-9])",
        value,
    )
    quoted = (
        match.group(1).strip() if match.group(1) else match.group(2).strip()
        for match in re.finditer(r"`([^`]{2,80})`|[\"']([^\"']{2,80})[\"']", value)
    )
    return tuple(dict.fromkeys([*labels, *quoted]))


def _retain_explicit_identifier_anchors(
    documents: list[Document], explicit_identifiers: tuple[str, ...]
) -> list[Document]:
    """Keep rare-term matches as candidates without forcing them into evidence."""

    normalized = tuple(value.casefold() for value in explicit_identifiers)
    for document in documents:
        searchable = " ".join(
            (document.page_content, str(document.metadata.get("title") or ""))
        ).casefold()
        if normalized and any(value in searchable for value in normalized):
            continue
        document.metadata.pop("identifier_anchor", None)
        document.metadata.pop("identifier_anchor_score", None)
        document.metadata["rare_term_match"] = True
    return documents


def _prefilter_candidates(
    documents: list[Document],
    minimum_dense_score: float = 0.30,
    maximum_removed_fraction: float = 0.34,
) -> tuple[list[Document], dict[str, int]]:
    """Remove non-responsive records before cross-encoder ranking.

    This filter exists to bound cross-encoder cost, so removal must be justified
    by a candidate being weak -- never by other candidates being strong. The
    previous rule dropped everything scoring below the pool's own median, which
    removes about half of any pool regardless of quality, and it keyed on zero
    literal term overlap, which is exactly the paraphrased match dense retrieval
    is for. Together those two properties preferentially discarded semantic hits
    from a healthy pool.

    Two invariants replace the median:

    * an absolute score floor, so a uniformly good pool loses nothing;
    * a ceiling on the removable fraction, so a mistuned floor degrades recall
      slightly instead of deleting content wholesale. When the ceiling binds, the
      weakest candidates go first and the best borderline ones survive.

    Structural exclusions (the vocabulary record, index pages without an
    identifier anchor) are not quality judgements and stay outside the ceiling.
    """

    kept: list[Document] = []
    reasons = {"index": 0, "vocabulary": 0, "zero_overlap_low_dense": 0}
    quality_candidates: list[Document] = []
    for document in documents:
        metadata = document.metadata
        if str(metadata.get("record_kind") or "") == "__vocabulary__":
            reasons["vocabulary"] += 1
            continue
        if (
            str(metadata.get("doc_category") or "narrative").casefold() == "index"
            and not metadata.get("identifier_anchor")
        ):
            reasons["index"] += 1
            continue
        quality_candidates.append(document)

    def _weak(document: Document) -> bool:
        metadata = document.metadata
        return (
            float(metadata.get("exact_term_ratio") or 0.0) == 0.0
            and float(metadata.get("score") or 0.0) < minimum_dense_score
            and not metadata.get("identifier_anchor")
            and not metadata.get("primary_query_rank")
            and not metadata.get("query_candidate_ranks")
        )

    removable = (
        [document for document in quality_candidates if _weak(document)]
        if len(documents) >= 8
        else []
    )
    ceiling = int(len(quality_candidates) * maximum_removed_fraction)
    if len(removable) > ceiling:
        # Drop the weakest first so the ceiling keeps the best borderline records.
        removable.sort(key=lambda value: float(value.metadata.get("score") or 0.0))
        removable = removable[:ceiling]
    removed = {id(document) for document in removable}
    for document in quality_candidates:
        if id(document) in removed:
            reasons["zero_overlap_low_dense"] += 1
            continue
        kept.append(document)
    return kept, reasons


def _source_volume_discounted_score(
    score: float, *, source_candidate_count: int, strength: float
) -> float:
    """Discount repeated opportunities from one source without excluding it.

    One candidate is neutral. Additional candidates increase the denominator
    logarithmically, bounded by the finite candidate-pool size and configured
    strength, so relevance can still make a high-volume source win.
    """

    repeated_candidates = max(0, source_candidate_count - 1)
    denominator = 1 + strength * math.log1p(repeated_candidates)
    return score / denominator


def _final_evidence_order(
    documents: list[Document], *, top_n: int, enumeration: bool
) -> list[Document]:
    """Keep registry depth for enumerations; diversify all other evidence windows."""

    ordered = documents if enumeration else _source_diverse_order(documents)
    return ordered[:top_n]


def _preserve_primary_query_candidates(
    ranked: list[Document], *, limit: int, reserve: int = 4,
    per_query_reserve: int = 8,
) -> list[Document]:
    """Keep a bounded window from every retrieval query for the cross-encoder.

    Query translations and decompositions improve recall, but reciprocal-rank
    fusion can reward generic chunks that appear for every expansion and evict
    the exact match found by the user's original wording. These records are not
    forced into final evidence; they are only guaranteed an opportunity to be
    scored by the cross-encoder.
    """

    primary = sorted(
        (
            document
            for document in ranked
            if int(document.metadata.get("primary_query_rank") or 0) > 0
        ),
        key=lambda document: int(document.metadata.get("primary_query_rank") or 0),
    )[: min(reserve, limit)]
    per_query: list[Document] = []
    query_indexes = sorted(
        {
            int(index)
            for document in ranked
            for index in (document.metadata.get("query_candidate_ranks") or {})
        }
    )
    for query_index in query_indexes:
        per_query.extend(
            sorted(
                (
                    document
                    for document in ranked
                    if str(query_index)
                    in (document.metadata.get("query_candidate_ranks") or {})
                ),
                key=lambda document: int(
                    (document.metadata.get("query_candidate_ranks") or {})[
                        str(query_index)
                    ]
                ),
            )[: min(per_query_reserve, limit)]
        )
    combined: list[Document] = []
    seen: set[str] = set()
    for document in [*primary, *per_query, *ranked]:
        identity = str(document.metadata.get("chunk_id") or _source_identity(document))
        if identity in seen:
            continue
        seen.add(identity)
        combined.append(document)
        if len(combined) >= limit:
            break
    return combined


def _preserve_identifier_anchors(
    ranked: list[Document], candidates: list[Document], *, top_n: int
) -> list[Document]:
    anchors = sorted(
        (document for document in candidates if document.metadata.get("identifier_anchor")),
        key=lambda item: float(item.metadata.get("identifier_anchor_score") or 0),
        reverse=True,
    )[: min(3, top_n)]
    combined: list[Document] = []
    seen: set[str] = set()
    for document in [*anchors, *ranked]:
        identity = str(document.metadata.get("chunk_id") or _source_identity(document))
        if identity in seen:
            continue
        seen.add(identity)
        if document.metadata.get("identifier_anchor"):
            document.metadata["rerank_score"] = 1.0
        combined.append(document)
        if len(combined) >= top_n:
            break
    return combined


def _inventory_identifier_anchors(
    candidates: list[Document], *, top_n: int
) -> list[Document]:
    """Deliver exact PAGE registry matches without redundant cross-encoding."""

    anchors = sorted(
        (
            document
            for document in candidates
            if document.metadata.get("identifier_anchor")
            and _document_source_type(document) == "PAGE"
        ),
        key=lambda item: float(
            item.metadata.get("identifier_anchor_score") or 0
        ),
        reverse=True,
    )[:top_n]
    for document in anchors:
        document.metadata["rerank_score"] = 1.0
    return anchors


def _fuse_reranked_groups(
    groups: list[list[Document]], *, top_n: int, rank_fusion_k: int
) -> list[Document]:
    """Merge qualifying reranks by maximum relevance plus reciprocal rank."""

    fused: dict[str, tuple[Document, float, float]] = {}
    for group in groups:
        for rank, document in enumerate(group, start=1):
            identity = str(document.metadata.get("chunk_id") or _source_identity(document))
            score = float(document.metadata.get("rerank_score") or 0.0)
            existing = fused.get(identity)
            rrf = (existing[2] if existing else 0.0) + 1 / (rank_fusion_k + rank)
            fused[identity] = (
                existing[0] if existing else document,
                max(existing[1] if existing else 0.0, score),
                rrf,
            )
    ordered = sorted(
        fused.values(), key=lambda item: (item[1] + item[2], item[1]), reverse=True
    )[:top_n]
    for document, score, rrf in ordered:
        document.metadata["rerank_score"] = score
        document.metadata["multilingual_rerank_rrf_score"] = rrf
    return [document for document, _score, _rrf in ordered]


def _candidate_id(document: Document) -> str:
    """Return the stable identity used to prove rerank inputs are unchanged."""

    return str(document.metadata.get("chunk_id") or "") or hashlib.sha256(
        (document.page_content + str(document.metadata.get("reference"))).encode()
    ).hexdigest()


def _same_rerank_inputs(state: RagState, query: str, candidates: list[Document]) -> bool:
    """Only identical scorer pairs permit reuse of the previous ranked result."""

    return (
        state.get("scored_query") == query
        and set(state.get("scored_candidate_ids", ()))
        == {_candidate_id(document) for document in candidates}
    )

class RetrievalNodesMixin:
    """RetrievalNodes responsibilities."""

    _sparse_retriever = BM25Retriever()
    _candidate_fusion = ReciprocalRankFusion()
    _context_evaluator = HeuristicContextEvaluator()

    async def _retrieve(self, state: RagState) -> RagState:
        began = started()
        self._last_source_type_scope_bypassed = False
        source_types = state.get("source_types", ())
        # One dense query per source type keeps a small family from being buried
        # by a large one. With no scope at all that fan-out has nothing to iterate,
        # and an empty `scopes` silently produced zero dense requests: retrieval
        # then ran on the lexical fallback alone, which reads as a healthy
        # `reason_code: OK` while the primary arm never executed. An unrestricted
        # scope is one request over every source type, never no request.
        per_source_fan_out = state.get("query_intent") in {
            "CROSS_SOURCE",
            "CODE_ASSISTED",
        } and bool(source_types)
        scopes = (
            tuple((source_type,) for source_type in source_types)
            if per_source_fan_out
            else (source_types,)
        )
        # Query planners can emit the same effective query from multiple
        # branches.  Execute each (query, scope) pair once per request so
        # retries/expansions do not duplicate provider calls or distort rank
        # fusion.  This is a request-local cache, so it never leaks data
        # between tenants or projects.
        requests = list(
            dict.fromkeys(
                (query, scope)
                for query in state["queries"]
                for scope in scopes
            )
        )
        resolved_question = state.get("resolved_question", self._request.question)
        exact_identifiers = _exact_identifier_tokens(
            resolved_question, self._vocabulary.entities
        )
        # Execute deterministic structured/lexical channels before semantic
        # retrieval. Semantic similarity expands recall inside the selected
        # scope; it is never proof and never substitutes for an exact match.
        exact_loader = getattr(self._retriever, "ainvoke_exact_identifiers", None)
        anchored = (
            await exact_loader(exact_identifiers, source_types)
            if exact_loader is not None and exact_identifiers
            else []
        )
        lexical_loader = getattr(self._retriever, "ainvoke_lexical", None)
        lexical_candidates = (
            await lexical_loader(resolved_question, source_types)
            if lexical_loader is not None
            else None
        )
        rare_loader = getattr(self._retriever, "ainvoke_rare_terms", None)
        rare_terms = (
            await rare_loader(resolved_question, source_types)
            if rare_loader is not None
            else ()
        )
        rare_lookups = tuple(
            value for value in rare_terms if value not in exact_identifiers
        )
        if exact_loader is not None and rare_lookups:
            anchored.extend(await exact_loader(rare_lookups, source_types))
        results = await asyncio.gather(
            *(self._retrieve_scope(query, scope) for query, scope in requests)
        )
        unique: dict[str, Document] = {}
        if state.get("preserve_candidates"):
            for document in state.get("candidates", []):
                identity = str(document.metadata.get("chunk_id") or "") or hashlib.sha256(
                    (document.page_content + str(document.metadata.get("reference"))).encode()
                ).hexdigest()
                unique[identity] = document
        query_indexes = {query: index for index, query in enumerate(state["queries"])}
        for (query, _scope), group in zip(requests, results, strict=True):
            for rank, document in enumerate(group, start=1):
                identity = str(document.metadata.get("chunk_id") or "") or hashlib.sha256(
                    (document.page_content + str(document.metadata.get("reference"))).encode()
                ).hexdigest()
                existing = unique.get(identity)
                if existing is None:
                    existing = document
                    existing.metadata["retrieval_rrf_score"] = 0.0
                    unique[identity] = existing
                existing.metadata["retrieval_rrf_score"] = float(
                    existing.metadata.get("retrieval_rrf_score", 0)
                ) + (1 / (self._settings.rank_fusion_k + rank))
                existing.metadata["score"] = max(
                    float(existing.metadata.get("score", 0)),
                    float(document.metadata.get("score", 0)),
                )
                query_ranks = dict(existing.metadata.get("query_candidate_ranks") or {})
                query_key = str(query_indexes[query])
                previous_query_rank = int(query_ranks.get(query_key) or 0)
                query_ranks[query_key] = (
                    min(previous_query_rank, rank) if previous_query_rank else rank
                )
                existing.metadata["query_candidate_ranks"] = query_ranks
                if query == resolved_question:
                    previous_primary_rank = int(
                        existing.metadata.get("primary_query_rank") or 0
                    )
                    existing.metadata["primary_query_rank"] = (
                        min(previous_primary_rank, rank)
                        if previous_primary_rank
                        else rank
                    )
        authorized = validate_authorized_candidates(
            list(unique.values()),
            project_id=self._request.project_id,
            access_policy_ids=self._request.access_policy_ids,
        )
        authorized = [
            document
            for document in authorized
            if str(document.metadata.get("doc_category") or "narrative") != "index"
            or bool(document.metadata.get("identifier_anchor"))
        ]
        # The retriever substitutes BM25 records into this same pool when a dense
        # provider call fails, so counting `authorized` reports a healthy dense
        # channel during a total embedding outage. Count only records that did not
        # arrive through the fallback.
        dense_candidates = [
            document
            for document in authorized
            if not document.metadata.get("retrieval_fallback")
        ]
        fallback_candidates = len(authorized) - len(dense_candidates)
        if lexical_candidates is None:
            lexical_candidates = self._sparse_retriever.rank(
                resolved_question, authorized
            )
        anchored = _retain_explicit_identifier_anchors(
            anchored, _forced_anchor_tokens(resolved_question)
        )
        for document in anchored:
            identity = str(document.metadata.get("chunk_id") or "") or hashlib.sha256(
                (document.page_content + str(document.metadata.get("reference"))).encode()
            ).hexdigest()
            document.metadata["retrieval_rrf_score"] = 1.0
            unique[identity] = document
            authorized.append(document)
        lexical_candidates = validate_authorized_candidates(
            lexical_candidates,
            project_id=self._request.project_id,
            access_policy_ids=self._request.access_policy_ids,
        )
        lexical_candidates = [
            document for document in lexical_candidates
            if str(document.metadata.get("doc_category") or "narrative") != "index"
            or bool(document.metadata.get("identifier_anchor"))
        ]
        dense_ranked = sorted(
            authorized,
            key=lambda value: float(value.metadata.get("retrieval_rrf_score", 0)),
            reverse=True,
        )
        fused_candidates = self._candidate_fusion.fuse(
            lexical_candidates,
            dense_ranked,
            limit=max(self._settings.max_candidates, self._settings.retrieval_top_k),
        )
        # RRF can omit an exact original-language match when generic records
        # recur across every translated/decomposed query. Reserve a small,
        # authorized original-query window before any subsequent filtering.
        primary_authorized = _preserve_primary_query_candidates(
            authorized,
            limit=min(
                len(authorized),
                max(self._settings.max_candidates, self._settings.retrieval_top_k),
            ),
        )
        fused_candidates = deduplicate_candidate_bodies(
            [*primary_authorized, *fused_candidates]
        )[: max(self._settings.max_candidates, self._settings.retrieval_top_k)]
        registry = SourcePolicyRegistry.from_categories(
            _document_source_type(document) for document in fused_candidates
        )
        fused_candidates = deduplicate_authoritative_versions(
            fused_candidates, registry
        )
        query_terms = _exact_terms(resolved_question)
        source_candidate_counts = Counter(
            _source_identity(document) for document in fused_candidates
        )
        for document in fused_candidates:
            exact_ratio = _exact_term_ratio(query_terms, document.page_content)
            document.metadata["exact_term_ratio"] = exact_ratio
            boosted_score = float(
                document.metadata.get("fusion_score", 0)
            ) * (1 + self._settings.exact_term_boost * exact_ratio)
            source_candidate_count = source_candidate_counts[
                _source_identity(document)
            ]
            document.metadata["source_candidate_count"] = source_candidate_count
            document.metadata["retrieval_fused_score"] = (
                _source_volume_discounted_score(
                    boosted_score,
                    source_candidate_count=source_candidate_count,
                    strength=self._settings.source_volume_discount_strength,
                )
            )
        responsive, prefilter_reasons = _prefilter_candidates(
            fused_candidates,
            minimum_dense_score=self._settings.prefilter_min_dense_score,
            maximum_removed_fraction=self._settings.prefilter_max_removed_fraction,
        )
        ranked_responsive = deduplicate_candidate_bodies(sorted(
            responsive,
            key=lambda value: float(value.metadata.get("retrieval_fused_score", 0)),
            reverse=True,
        ))
        candidates = _preserve_primary_query_candidates(
            ranked_responsive,
            limit=self._settings.max_candidates,
        )
        preserved_query_indexes = {
            str(index)
            for document in candidates
            for index, rank in (document.metadata.get("query_candidate_ranks") or {}).items()
            if int(rank) <= 8
        }
        preserved_candidate_count = sum(
            any(int(rank) <= 8 for rank in (document.metadata.get("query_candidate_ranks") or {}).values())
            for document in candidates
        )
        usage = self._retriever.drain_usage()
        stage_complete(
            "retrieve",
            self._request.project_id,
            began,
            input_count=len(requests),
            output_count=len(candidates),
            input_tokens=usage["embedding_tokens"],
            retry_count=usage["retry_count"],
            model_provider="chroma",
            model_name=self._request.embedding_model,
            model_profile="retrieval",
            language=state.get("language", "und"),
            extra={
                "read_units": usage["read_units"],
                "retrieval_attempt": state.get("retrieval_attempt", 1),
                "query_intent": state.get("query_intent", "DIRECT"),
                "source_route": state.get("source_route", "MIXED"),
                "code_candidates": _source_type_count(candidates, "CODE"),
                "page_candidates": _source_type_count(candidates, "PAGE"),
                "issue_candidates": _source_type_count(candidates, "ISSUE"),
                "attachment_candidates": _source_type_count(candidates, "ATTACHMENT"),
                "code_required": int(
                    "CODE" in _required_evidence_source_types(
                        state.get("query_intent", "DIRECT")
                    )
                ),
                "lexical_candidate_count": len(lexical_candidates),
                "dense_candidate_count": len(dense_candidates),
                # Hybrid retrieval running on one leg is a serious degradation
                # that used to be indistinguishable from a healthy empty search.
                "dense_arm_status": (
                    "NO_REQUESTS_ISSUED"
                    if not requests
                    else "EMPTY_RESULT"
                    if not dense_candidates
                    else "OK"
                ),
                "fallback_candidate_count": fallback_candidates,
                "fused_candidate_count": len(fused_candidates),
                "prefiltered_count": len(fused_candidates) - len(responsive),
                "prefiltered_reasons": prefilter_reasons,
                "query_variant_count": len(state["queries"]),
                "queries_with_preserved_candidates": len(preserved_query_indexes),
                "preserved_candidate_count": preserved_candidate_count,
                "entity_vocabulary_size": len(self._vocabulary.entities),
                "entity_capability": (
                    "enabled" if self._vocabulary.entities else "disabled"
                ),
            },
        )
        return {
            "candidates": candidates,
            "preserve_candidates": False,
            "lexical_candidate_count": len(lexical_candidates),
            "dense_candidate_count": len(dense_candidates),
            "fallback_candidate_count": fallback_candidates,
            "fused_candidate_count": len(fused_candidates),
            "prefiltered_count": len(fused_candidates) - len(responsive),
        }

    async def _retrieve_scope(
        self, query: str, source_types: tuple[str, ...]
        ) -> list[Document]:
        """Keep lightweight test retrievers compatible while production stays scoped."""

        scoped = getattr(self._retriever, "ainvoke_scoped", None)
        if scoped is not None:
            return await scoped(query, source_types)
        documents = await self._retriever.ainvoke(query)
        if len(source_types) == 1:
            for document in documents:
                if _document_source_type(document) in {"", "DOCUMENT"}:
                    document.metadata["source_type"] = source_types[0]
        return documents

    async def _feature_affinity(self, state: RagState) -> RagState:
        """Prefer an exact classified feature page when the question names one.

        This is deliberately deterministic. Authorization remains enforced by the
        retriever, while title affinity prevents a related page from displacing
        the exact feature page.
        """

        began = started()
        candidates = state.get("candidates", [])
        overview_entity = state.get("overview_entity", "")
        project_overview = state.get("query_intent") == "PROJECT_OVERVIEW"
        if project_overview:
            selected = [
                document
                for document in candidates
                if not _low_information_project_document(document)
            ]
            matching_source_ids = {_source_identity(document) for document in selected}
            reason_code = (
                "PROJECT_PLACEHOLDERS_REMOVED"
                if len(selected) < len(candidates)
                else "PROJECT_EVIDENCE_KEPT"
            )
        elif overview_entity:
            matching_source_ids = _entity_overview_source_ids(overview_entity, candidates)
        else:
            matching_source_ids = _exact_feature_source_ids(
                state.get("resolved_question", self._request.question), candidates
            )
        if not project_overview and matching_source_ids:
            selected = [
                document
                for document in candidates
                if _source_identity(document) in matching_source_ids
            ]
            reason_code = (
                "FEATURE_INVENTORY_MATCH"
                if state.get("query_intent") == "FEATURE_INVENTORY"
                else "ENTITY_OVERVIEW_MATCH"
                if overview_entity
                else "EXACT_FEATURE_TITLE"
            )
        elif not project_overview:
            selected = candidates
            reason_code = (
                "NO_ENTITY_OVERVIEW_MATCH" if overview_entity else "NO_EXACT_FEATURE_TITLE"
            )
        stage_complete(
            "feature_affinity",
            self._request.project_id,
            began,
            input_count=len(candidates),
            output_count=len(selected),
            reason_code=reason_code,
            language=state.get("language", "und"),
            extra={
                "matching_source_count": len(matching_source_ids),
                "query_intent": state.get("query_intent", "DIRECT"),
                "entity": overview_entity.upper() if overview_entity else "NONE",
            },
        )
        return {
            "candidates": selected,
            "feature_affinity_applied": bool(matching_source_ids),
        }

    async def _rerank(self, state: RagState) -> RagState:
        """Apply intent-specific local ranking to a bounded candidate set."""

        began = started()
        candidates = state.get("candidates", [])
        if state.get("query_intent") == "ENTITY_OVERVIEW":
            candidates = candidates[: self._settings.retrieval_top_k]
        inventory_question = is_inventory_question(self._request.question)
        all_candidates = list(candidates)
        rerank_query = state.get("rerank_query", self._request.question)
        rerank_queries = state.get("rerank_queries", (rerank_query,))
        candidate_ids = tuple(sorted(_candidate_id(document) for document in all_candidates))
        if state.get("prior_documents") is not None and _same_rerank_inputs(
            state, rerank_query, all_candidates
        ):
            documents = list(state.get("prior_documents", []))
            stage_complete(
                "rerank",
                self._request.project_id,
                began,
                input_count=len(all_candidates),
                output_count=len(documents),
                reason_code="IDENTICAL_REPAIR_INPUTS",
                model_provider="deterministic",
                model_name="prior-rerank-result",
                model_profile="rerank",
                language=state.get("language", "und"),
                extra={"repair_rerank_skipped": True},
            )
            return {
                "documents": documents,
                "scored_query": rerank_query,
                "scored_candidate_ids": candidate_ids,
                "rerank_skipped": True,
            }
        # CODE_ASSISTED is the default route -- anything that is not an overview,
        # an inventory, an implementation or a delivery question lands here -- so a
        # hard-coded 4 was the tightest evidence limit in the system and applied to
        # most questions. It ignored PI_RAG_RERANK_TOP_N entirely: a corpus with 99
        # chunks about events answered an inventory question from four of them,
        # spending 1,631 of a 16,000-token evidence budget. The narrower window was
        # a precision heuristic for mixed PAGE+CODE routes, so it stays available as
        # a setting rather than a literal.
        result_top_n = (
            max(3, self._settings.rerank_top_n)
            if state.get("query_intent") == "PROJECT_OVERVIEW"
            else self._settings.feature_inventory_top_n
            if state.get("query_intent") in {"FEATURE_INVENTORY", "CODE_INVENTORY"}
            else self._settings.mixed_source_top_n
            if state.get("query_intent") in {"CROSS_SOURCE", "CODE_ASSISTED"}
            else self._settings.rerank_top_n
        )
        procedural_question = is_procedural_question(self._request.question)
        evidence_rich_single_source = (
            state.get("query_intent")
            in {"STRUCTURED_INVENTORY", "ENTITY_OVERVIEW", "FEATURE_INVENTORY", "CODE_INVENTORY"}
            or any(
                str(document.metadata.get("doc_category") or "").casefold()
                in {"entity-contract", "registry-table"}
                for document in candidates
            )
        )
        intent_source_limit = (
            max(result_top_n, self._settings.max_chunks_per_source)
            if evidence_rich_single_source
            else self._settings.max_chunks_per_source
        )
        code_location_documents = (
            sorted(
                (
                    document
                    for document in candidates
                    if _code_location_document_score(
                        rerank_query, document, self._vocabulary.code_extensions
                    ) > 0
                ),
                key=lambda document: _code_location_document_score(
                    rerank_query, document, self._vocabulary.code_extensions
                ),
                reverse=True,
            )[:result_top_n]
            if state.get("query_intent") == "IMPLEMENTATION"
            else []
        )
        singleton_delivery = (
            state.get("query_intent") == "DELIVERY" and len(candidates) == 1
        )
        exact_inventory_documents = (
            _inventory_identifier_anchors(all_candidates, top_n=result_top_n)
            if state.get("query_intent") == "STRUCTURED_INVENTORY"
            else []
        )
        if inventory_question:
            candidates = balanced_source_candidate_pool(
                all_candidates,
                self._settings.inventory_cross_encoder_candidate_limit,
            )
        elif procedural_question:
            candidates = balanced_source_candidate_pool(
                all_candidates,
                max(result_top_n * 3, self._settings.cross_encoder_candidate_limit),
            )
        elif state.get("query_intent") not in {
            "FEATURE_INVENTORY",
            "CODE_INVENTORY",
            "PROJECT_OVERVIEW",
        }:
            candidates = progressive_rerank_candidates(
                candidates,
                max(result_top_n, self._settings.cross_encoder_candidate_limit),
            )
        if code_location_documents:
            documents = code_location_documents
            for document in documents:
                document.metadata["rerank_score"] = float(
                    document.metadata.get("score", 0)
                )
        elif singleton_delivery:
            # An ISSUE-only search with one authorized candidate cannot be reordered.
            # Preserve its retrieval score and avoid invoking the cross-encoder.
            documents = candidates[:1]
            documents[0].metadata["rerank_score"] = float(
                documents[0].metadata.get("score", 0)
            )
        elif exact_inventory_documents:
            documents = exact_inventory_documents
        elif state.get("query_intent") == "PROJECT_OVERVIEW":
            documents = await self._rerank_project_overview(state, candidates)
        elif state.get("query_intent") == "FEATURE_INVENTORY":
            documents = await self._reranker.rerank(
                rerank_query,
                candidates,
                score_threshold=0.0,
                top_n=len(candidates),
                max_chunks_per_source=self._settings.feature_inventory_top_n,
                query_language=state.get("language", ""),
            )
            if inventory_question:
                # Generic inventories do not have an entity key. The entity-aware
                # selector intentionally rejects such evidence, which previously
                # turned a valid shortcut/configuration inventory into zero results.
                documents = _merge_ranked_documents(
                    documents,
                    candidates,
                    top_n=self._settings.feature_inventory_top_n,
                )
            else:
                documents = _inventory_documents(
                    [*documents, *candidates],
                    state.get("overview_entity", ""),
                )[
                    : self._settings.feature_inventory_top_n
                ]
        elif state.get("query_intent") == "CODE_INVENTORY":
            verified_candidates = _code_inventory_documents(
                candidates,
                self._settings.feature_inventory_top_n,
                self._request.question,
            )
            documents = await self._reranker.rerank(
                rerank_query,
                verified_candidates,
                score_threshold=0.0,
                top_n=len(verified_candidates),
                max_chunks_per_source=self._settings.feature_inventory_top_n,
            )
            documents = _code_inventory_documents(
                documents,
                self._settings.feature_inventory_top_n,
                self._request.question,
            )
        elif procedural_question:
            ranked_groups = [
                await rerank_source_families(
                    self._reranker, query, candidates, top_n=result_top_n
                )
                for query in rerank_queries
            ]
            documents = _fuse_reranked_groups(
                ranked_groups,
                top_n=result_top_n,
                rank_fusion_k=self._settings.rank_fusion_k,
            )
        elif state.get("query_intent") == "CODE_ASSISTED":
            documents = await self._rerank_code_assisted(
                rerank_query,
                candidates,
                intent_source_limit,
                rerank_queries=rerank_queries,
                language=state.get("language", ""),
            )
        elif state.get("query_intent") == "STRUCTURED_INVENTORY":
            documents = await self._rerank_code_assisted(
                rerank_query,
                candidates,
                intent_source_limit,
                language=state.get("language", ""),
            )
        elif state.get("query_intent") == "CROSS_SOURCE":
            documents = await self._rerank_cross_source(
                rerank_query, candidates, state.get("language", "")
            )
        elif state.get("query_intent") == "ENTITY_OVERVIEW":
            try:
                documents = await self._reranker.rerank(
                    rerank_query,
                    candidates,
                    score_threshold=0.0,
                    top_n=len(candidates),
                    max_chunks_per_source=intent_source_limit,
                )
            except TypeError as error:
                if "top_n" not in str(error):
                    raise
                documents = await self._reranker.rerank(
                    rerank_query,
                    candidates,
                    score_threshold=self._settings.entity_overview_rerank_score_threshold,
                )
            documents = _source_diverse_order(documents)[:result_top_n]
        elif state.get("query_intent") == "IMPLEMENTATION":
            # Rank a wider code window before applying the executable-file preference.
            # With the normal final limit of two, repository README chunks can otherwise
            # consume both slots and discard the relevant source file even when Chroma
            # retrieved it. The final merge below still enforces the configured response
            # evidence limit.
            implementation_window = min(len(candidates), max(8, result_top_n))
            try:
                documents = await self._reranker.rerank(
                    rerank_query,
                    candidates,
                    top_n=implementation_window,
                )
            except TypeError as error:
                # Keep lightweight/custom rerankers that implement the older protocol
                # usable while production rerankers accept the explicit window.
                if "top_n" not in str(error):
                    raise
                documents = await self._reranker.rerank(rerank_query, candidates)
            documents = _implementation_evidence_order(
                documents, rerank_query, self._vocabulary.code_extensions
            )
        else:
            documents = await self._reranker.rerank(
                rerank_query,
                candidates,
                max_chunks_per_source=intent_source_limit,
            )
        documentation_primary = state.get("query_intent") in {
            "CODE_ASSISTED",
            "STRUCTURED_INVENTORY",
            "FEATURE_INVENTORY",
        }
        # CODE_ASSISTED and STRUCTURED_INVENTORY now rank both source families in a
        # single cross-encoder pass, so re-imposing PAGE-first order and the code cap
        # after selection would silently undo that. FEATURE_INVENTORY keeps its
        # reserved-slot ordering until it is measured separately.
        documentation_reserved_slots = (
            state.get("query_intent") == "FEATURE_INVENTORY"
        )
        # An exact identifier match is protected regardless of source family. This
        # used to exclude CODE whenever documentation was primary, so a Kotlin file
        # containing the literal constant got no anchor protection while a page
        # merely mentioning it did -- payload questions then cited prose instead of
        # the declaration. documentation_primary still governs the ordering
        # decisions below; it no longer governs anchor eligibility.
        documents = _preserve_identifier_anchors(
            documents, all_candidates, top_n=result_top_n
        )
        if (
            self._settings.neighbor_expansion_enabled
            and documents
            and state.get("query_intent")
            not in {
                "ENTITY_OVERVIEW",
                "PROJECT_OVERVIEW",
                "FEATURE_INVENTORY",
                "CODE_INVENTORY",
                "CROSS_SOURCE",
            }
        ):
            documents = _expand_candidate_neighbors(
                documents,
                all_candidates,
                top_n=result_top_n,
                max_per_anchor=self._settings.max_neighbors_per_anchor,
                max_per_source=self._settings.max_chunks_per_source,
            )
        if state.get("query_intent") == "FEATURE_INVENTORY":
            if not inventory_question:
                documents = _inventory_documents(
                    documents,
                    state.get("overview_entity", ""),
                )
        elif state.get("query_intent") == "CODE_INVENTORY":
            documents = _code_inventory_documents(
                documents,
                self._settings.feature_inventory_top_n,
                self._request.question,
            )
        elif state.get("query_intent") == "ENTITY_OVERVIEW":
            documents = _source_diverse_order(documents)
        elif state.get("query_intent") == "PROJECT_OVERVIEW":
            documents = _project_overview_evidence_order(documents)
        if documentation_reserved_slots:
            primary = [
                document
                for document in documents
                if _document_source_type(document) == "PAGE"
            ]
            supporting = [
                document
                for document in documents
                if _document_source_type(document) != "PAGE"
            ][: self._settings.code_assisted_code_top_n]
            if primary:
                documents = [
                    *primary[: max(1, result_top_n - len(supporting))],
                    *supporting,
                ]
        if not documents and candidates:
            # The rerank threshold is a cost and quality prefilter, not the truth
            # gate -- grounding is. When it empties the pool the request fails
            # with INSUFFICIENT_EVIDENCE while the evidence sits in `candidates`
            # unseen, which is what happened to two questions whose answers were
            # in the corpus. Score once more without the floor and let grounding
            # decide; a question with genuinely no support still refuses there,
            # one stage later and for the right reason.
            documents = await self._reranker.rerank(
                rerank_query,
                candidates,
                top_n=result_top_n,
                query_language=state.get("language", ""),
                allow_threshold_bypass=True,
            )
        documents = _merge_ranked_documents(
            documents,
            state.get("prior_documents", []),
            top_n=result_top_n,
        )
        documents = _include_repair_evidence(
            documents,
            all_candidates,
            state.get("repair_requirements", ()),
            top_n=result_top_n,
        )
        if documentation_reserved_slots:
            primary = [
                document
                for document in documents
                if _document_source_type(document) == "PAGE"
            ]
            supporting = [
                document
                for document in documents
                if _document_source_type(document) != "PAGE"
            ][: self._settings.code_assisted_code_top_n]
            if primary:
                documents = [
                    *primary[: max(1, result_top_n - len(supporting))],
                    *supporting,
                ]
        # Enumeration answers often live across consecutive chunks of one
        # registry. Preserve their relevance depth; for other questions, fill
        # the window by source depth so one source does not dominate by volume.
        documents = _final_evidence_order(
            documents,
            top_n=result_top_n,
            enumeration=inventory_question,
        )
        pre_reconstruction_count = len(documents)
        if state.get("reconstruct_parent_records") or state.get("query_intent") in {
            "STRUCTURED_ENTITY",
            "STRUCTURED_INVENTORY",
        }:
            documents = await self._reconstruct_parent_records(
                documents, state.get("source_types", ())
            )
        else:
            documents = documents[:result_top_n]
        post_reconstruction_count = len(documents)
        requested_entities = {
            str(entity).casefold()
            for entity in self._vocabulary.entities
            if re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(str(entity))}(?![A-Za-z0-9_])",
                state.get("resolved_question", self._request.question),
                re.IGNORECASE,
            )
        }
        declared_entities: set[str] = set()
        for document in documents:
            declared = str(document.metadata.get("entity") or "").casefold().strip()
            if declared:
                declared_entities.add(declared)
                continue
            identity_text = " ".join(
                str(document.metadata.get(field) or "")
                for field in ("title", "path", "reference")
            )
            declared_entities.update(
                str(entity).casefold()
                for entity in self._vocabulary.entities
                if re.search(
                    rf"(?<![A-Za-z0-9_]){re.escape(str(entity))}(?![A-Za-z0-9_])",
                    identity_text,
                    re.IGNORECASE,
                )
            )
        uncertain_entity = str(state.get("uncertain_entity_token") or "")
        entity_mismatch = (
            len(requested_entities) == 1
            and len(declared_entities) == 1
            and requested_entities.isdisjoint(declared_entities)
            and all(str(document.metadata.get("entity") or "").strip() for document in documents)
        )
        uncertain_mismatch = bool(
            uncertain_entity and len(declared_entities) == 1 and declared_entities
        )
        entity_mismatch = entity_mismatch or uncertain_mismatch
        mismatch_requested = (
            uncertain_entity
            if uncertain_mismatch
            else next(iter(requested_entities), "") if entity_mismatch else ""
        )
        mismatch_suggested = next(iter(declared_entities), "") if entity_mismatch else ""
        if entity_mismatch:
            documents = []
        stage_complete(
            "rerank",
            self._request.project_id,
            began,
            input_count=len(all_candidates),
            output_count=len(documents),
            reason_code=(
                "CODE_LOCATION_MATCH"
                if code_location_documents
                else "EXACT_IDENTIFIER_ANCHOR"
                if exact_inventory_documents
                else "SINGLE_CANDIDATE_PASSTHROUGH"
                if singleton_delivery
                else "CAPPED_BY_SOURCE_LIMIT"
                if int(getattr(self._reranker, "last_capped_by_source_limit", 0)) > 0
                else "OK"
                if documents
                else "INSUFFICIENT_EVIDENCE"
            ),
            retry_count=int(getattr(self._reranker, "last_retry_count", 0)),
            model_provider=(
                "deterministic"
                if code_location_documents
                or singleton_delivery
                or exact_inventory_documents
                else "local"
            ),
            model_name=(
                "code-location-match"
                if code_location_documents
                else "exact-identifier-anchor"
                if exact_inventory_documents
                else "single-candidate-passthrough"
                if singleton_delivery
                else self._settings.local_rerank_model
            ),
            model_profile="rerank",
            language=state.get("language", "und"),
            extra={
                "query_intent": state.get("query_intent", "DIRECT"),
                "entity": state.get("overview_entity", "").upper() or "NONE",
                "source_route": state.get("source_route", "MIXED"),
                "code_candidates": _source_type_count(candidates, "CODE"),
                "page_candidates": _source_type_count(candidates, "PAGE"),
                "code_selected": _source_type_count(documents, "CODE"),
                "page_selected": _source_type_count(documents, "PAGE"),
                "issue_selected": _source_type_count(documents, "ISSUE"),
                "attachment_selected": _source_type_count(documents, "ATTACHMENT"),
                "primary_selected": _source_type_count(documents, "PAGE")
                if documentation_primary
                else len(documents),
                "supporting_selected": _source_type_count(documents, "CODE")
                if documentation_primary
                else 0,
                "capped_by_source_limit": int(
                    getattr(self._reranker, "last_capped_by_source_limit", 0)
                ),
                "source_cap_bypassed": int(
                    getattr(self._reranker, "last_source_cap_bypassed", False)
                ),
                "source_type_scope_bypassed": int(
                    getattr(self, "_last_source_type_scope_bypassed", False)
                ),
                "pre_reconstruction_count": pre_reconstruction_count,
                "post_reconstruction_count": post_reconstruction_count,
                "entity_mismatch_clarification": entity_mismatch,
            },
        )
        return {
            "documents": documents,
            "scored_query": rerank_query,
            "scored_candidate_ids": candidate_ids,
            "rerank_skipped": False,
            "entity_mismatch_requested": mismatch_requested,
            "entity_mismatch_suggested": mismatch_suggested,
        }

    async def _reconstruct_parent_records(
        self, documents: list[Document], source_types: tuple[str, ...]
    ) -> list[Document]:
        """Replace matching chunks with their complete authorized parent version."""

        loader = getattr(self._retriever, "ainvoke_source_siblings", None)
        parent_ids = {
            str(document.metadata.get("parent_id") or "")
            for document in documents
            if document.metadata.get("parent_id")
        }
        if loader is None or not parent_ids:
            return documents
        siblings = await loader(
            tuple(dict.fromkeys(parent_ids)),
            source_types,
        )
        matching = deduplicate_authoritative_versions(
            [*documents, *siblings],
            SourcePolicyRegistry.from_categories(
                _document_source_type(document) for document in [*documents, *siblings]
            ),
        )
        matching = [
            document
            for document in matching
            if str(document.metadata.get("parent_id") or "") in parent_ids
        ]
        if not matching:
            return documents
        by_parent: dict[str, list[Document]] = {}
        for document in matching:
            key = str(document.metadata.get("parent_id") or "")
            by_parent.setdefault(key, []).append(document)
        result: list[Document] = []
        seen_chunks: set[str] = set()
        emitted_parents: set[str] = set()
        for anchor in documents:
            key = str(anchor.metadata.get("parent_id") or "")
            family = by_parent.get(key, [anchor]) if key else [anchor]
            if key in emitted_parents:
                continue
            emitted_parents.add(key)
            for document in sorted(
                family, key=lambda item: int(item.metadata.get("chunk_ordinal") or 0)
            ):
                identity = str(document.metadata.get("chunk_id") or "") or hashlib.sha256(
                    (document.page_content + str(document.metadata.get("reference") or "")).encode()
                ).hexdigest()
                if identity not in seen_chunks:
                    seen_chunks.add(identity)
                    result.append(document)
        return result

    async def _rerank_cross_source(
        self, query: str, candidates: list[Document], language: str = ""
        ) -> list[Document]:
        """Rank documentation and code independently before a bounded merge."""

        groups: list[list[Document]] = []
        for source_type in ("PAGE", "CODE"):
            scoped = [
                document
                for document in candidates
                if _document_source_type(document) == source_type
            ]
            # Same reasoning as the code-assisted route: a per-family cap that
            # reserves room for the other family is wasted when the other family
            # is empty.
            other = [
                document
                for document in candidates
                if _document_source_type(document) != source_type
            ]
            window = (
                min(len(scoped), self._settings.mixed_source_top_n)
                if not other
                else min(self._settings.code_assisted_page_top_n, len(scoped))
            )
            ranked = await self._reranker.rerank(
                query, scoped, top_n=window, query_language=language
            )
            groups.append(ranked)
        merged: list[Document] = []
        for rank in range(max((len(group) for group in groups), default=0)):
            for group in groups:
                if rank < len(group):
                    merged.append(group[rank])
        return merged

    async def _rerank_code_assisted(
        self,
        query: str,
        candidates: list[Document],
        source_limit: int,
        *,
        rerank_queries: tuple[str, ...] = (),
        language: str = "",
        ) -> list[Document]:
        """Rank documentation and code together on relevance, with no reserved slots.

        PAGE and CODE used to be reranked in separate calls and merged as
        ``[*pages, *code]`` under per-family caps, so their scores were never
        compared and code could never exceed two documents however well it scored.
        The application source is authoritative for declarations, so both families
        now compete in one cross-encoder pass. ``source_limit`` still prevents a
        single file from supplying the whole window.
        """

        # Removing the per-family quota must not remove the family *scope*. This
        # route answers from documentation and code; delivery tickets belong to
        # DELIVERY. An empty scoped set must remain empty and fail closed.
        scoped = [
            document
            for document in candidates
            if _document_source_type(document) in {"PAGE", "CODE"}
        ]
        selected: list[Document] = []
        if scoped:
            try:
                groups = [
                    await self._reranker.rerank(
                        rerank_query,
                        scoped,
                        top_n=self._settings.mixed_source_top_n,
                        max_chunks_per_source=source_limit,
                        query_language=language,
                    )
                    for rerank_query in (rerank_queries or (query,))
                ]
                selected = _fuse_reranked_groups(
                    groups,
                    top_n=self._settings.mixed_source_top_n,
                    rank_fusion_k=self._settings.rank_fusion_k,
                )
            except TypeError as error:
                if "top_n" not in str(error):
                    raise
                selected = (await self._reranker.rerank(query, scoped))[
                    : self._settings.mixed_source_top_n
                ]
        # Executable files still outrank repository prose -- READMEs and design
        # notes committed beside the code. That judgement is about code quality,
        # not about code versus documentation, so it is applied only among the
        # code slots and leaves each slot's rank position intact.
        code_slots = [
            index
            for index, document in enumerate(selected)
            if _document_source_type(document) == "CODE"
        ]
        if len(code_slots) > 1:
            ordered_code = _implementation_evidence_order(
                [selected[index] for index in code_slots],
                query,
                self._vocabulary.code_extensions,
            )
            for index, document in zip(code_slots, ordered_code):
                selected[index] = document
        self._last_source_type_scope_bypassed = False
        return selected

    async def _rerank_project_overview(
        self, state: RagState, candidates: list[Document]
        ) -> list[Document]:
        """Fuse focused reranks so one broad wording cannot suppress all evidence."""

        fused: dict[str, Document] = {}
        # Bounded like every other route. This fused one rerank pass per corpus
        # entity over the whole candidate pool, so a 14-entity vocabulary meant
        # ~15 passes and 53 seconds of cross-encoder time for a single question.
        # The retrieval side of this same route already slices its query list to
        # max_query_variants; the rerank side not doing so was an oversight, not
        # a design choice.
        overview_queries = tuple(
            state.get("project_rerank_queries", state.get("queries", ()))
        )[: self._settings.max_query_variants]
        for query in overview_queries:
            ranked = await self._reranker.rerank(
                query,
                candidates,
                score_threshold=self._settings.entity_overview_rerank_score_threshold,
                query_language=state.get("language", ""),
                allow_threshold_bypass=True,
            )
            for rank, document in enumerate(ranked, start=1):
                identity = str(document.metadata.get("chunk_id") or _source_identity(document))
                existing = fused.setdefault(identity, document)
                existing.metadata["project_rerank_rrf_score"] = float(
                    existing.metadata.get("project_rerank_rrf_score", 0)
                ) + (1 / (self._settings.rank_fusion_k + rank))
                existing.metadata["project_rerank_score"] = max(
                    float(existing.metadata.get("project_rerank_score", 0)),
                    float(document.metadata.get("rerank_score", 0)),
                )
        ordered = sorted(
            fused.values(),
            key=lambda document: (
                float(document.metadata.get("project_rerank_rrf_score", 0)),
                float(document.metadata.get("project_rerank_score", 0)),
            ),
            reverse=True,
        )
        for document in ordered:
            document.metadata["rerank_score"] = float(
                document.metadata.get("project_rerank_score", 0)
            )
        return _project_overview_evidence_order(ordered)[: max(3, self._settings.rerank_top_n)]

    def _route_after_rerank(self, state: RagState) -> str:
        if state.get("documents"):
            return "validate_evidence"
        if (
            self._settings.adaptive_query_enabled
            and state.get("retrieval_attempt", 1) < self._settings.max_retrieval_attempts
        ):
            return "recover_query"
        return "end"

    async def _validate_evidence_completeness(self, state: RagState) -> RagState:
        began = started()
        requirements = _answer_requirements(
            self._request.question, self._vocabulary.entities
        )
        missing = _missing_evidence_requirements(requirements, state.get("documents", []))
        required_source_types = _required_evidence_source_types(
            state.get("query_intent", "DIRECT")
        )
        present_source_types = {
            _document_source_type(document) for document in state.get("documents", [])
        }
        missing = (
            *missing,
            *(
                f"source:{source_type}"
                for source_type in required_source_types
                if source_type not in present_source_types
            ),
        )
        quality = self._context_evaluator.evaluate(
            state.get("resolved_question", self._request.question),
            state.get("documents", []),
            relevance_threshold=self._settings.context_relevance_threshold,
        )
        # ``missing_information`` is explanatory prose from the cheap context
        # heuristic, not a machine-readable requirement.  Keep it as a quality
        # signal, but never let a sentence such as "more specific supporting
        # evidence" enter the repair requirement loop.
        context_missing_signal_count = len(quality.missing_information)
        exhausted = bool(missing) and state.get("retrieval_attempt", 1) >= self._settings.max_retrieval_attempts
        stage_complete(
            "evidence_completeness",
            self._request.project_id,
            began,
            input_count=len(requirements),
            output_count=0 if missing else 1,
            reason_code=(
                "COMPLETE"
                if not missing
                else "INCOMPLETE_EXHAUSTED"
                if exhausted
                else "INCOMPLETE_REPAIRABLE"
            ),
            language=state.get("language", "und"),
            extra={
                "missing_requirement_count": len(missing),
                "context_quality": quality.quality,
                "context_relevance": quality.relevance,
                "context_completeness": quality.completeness,
                "context_failure_reason": quality.failure_reason,
                "context_missing_signal_count": context_missing_signal_count,
            },
        )
        result: RagState = {
            "missing_requirements": missing,
            "context_quality": quality.quality,
            "context_relevance": quality.relevance,
            "context_completeness": quality.completeness,
            "context_failure_reason": quality.failure_reason,
        }
        # Only a genuinely empty pool is a fail-closed condition here. Marking a
        # populated pool ungrounded ends the request before generation, so the
        # gates that actually judge truth never see the evidence.
        if exhausted and not state.get("documents"):
            result["grounded"] = False
            result["grounding_reason"] = "INCOMPLETE_EVIDENCE"
        return result

    def _route_after_evidence_completeness(self, state: RagState) -> str:
        if state.get("grounded") is False:
            return "generate" if state.get("documents") else "end"
        if not state.get("missing_requirements"):
            return "generate"
        if state.get("retrieval_attempt", 1) < self._settings.max_retrieval_attempts:
            return "repair_completeness"
        # This floor is derived below every answered-and-grounded Layer 1 case.
        # It is consulted only after bounded repair is exhausted, so borderline
        # evidence still gets the same repair and truth-gate path as before.
        if (
            float(state.get("context_relevance") or 0.0)
            < self._settings.context_relevance_floor
        ):
            return "end"
        return "generate" if state.get("documents") else "end"
