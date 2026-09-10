from __future__ import annotations

from typing import TypedDict

from langchain_core.documents import Document

from app.llm import GroundedAnswer
from app.models import RagRequest, ResolvedRequest

class RagState(TypedDict, total=False):
    _workflow: object
    request: RagRequest
    queries: tuple[str, ...]
    language: str
    candidates: list[Document]
    documents: list[Document]
    generated: GroundedAnswer
    answer_style: str
    canonical_fallback_used: bool
    canonical_fallback_reason: str
    canonical_route_refusal_reason: str
    generated_outcome: str
    generated_refusal_reason: str
    retrieval_attempt: int
    repaired: bool
    grounded: bool
    grounding_reason: str
    missing_requirements: tuple[str, ...]
    preserve_candidates: bool
    feature_affinity_applied: bool
    repair_requirements: tuple[str, ...]
    prior_documents: list[Document]
    query_intent: str
    overview_entity: str
    rerank_query: str
    rerank_queries: tuple[str, ...]
    translation_slot: int | None
    project_rerank_queries: tuple[str, ...]
    source_types: tuple[str, ...]
    source_route: str
    # Set when recovery widened a source scope that returned no candidates.
    source_scope_widened: bool
    resolved_question: str
    resolved_request: ResolvedRequest
    query_quality: str
    query_quality_reason: str
    lexical_candidate_count: int
    dense_candidate_count: int
    fallback_candidate_count: int
    fused_candidate_count: int
    prefiltered_count: int
    context_quality: str
    context_relevance: float
    context_completeness: float
    context_failure_reason: str
    answer_relevance: float
    answer_relevance_query: str
    coverage_expected: int
    coverage_expected_identifiers: tuple[str, ...]
    coverage_expected_fields: tuple[str, ...]
    coverage_covered: int
    coverage_missing: tuple[str, ...]
    coverage_missing_fields: tuple[str, ...]
    population_retrieval_miss: bool
    stream_truncated: bool
    uncited_claims_dropped: int
    output_gate_applied: bool
    reconstruct_parent_records: bool
    entity_mismatch_requested: str
    entity_mismatch_suggested: str
    uncertain_entity_token: str
