from langchain_core.documents import Document
import pytest

from app.retrieval_pipeline import (
    BM25Retriever,
    HeuristicContextEvaluator,
    ReciprocalRankFusion,
    deduplicate_candidate_bodies,
    validate_authorized_candidates,
)


def document(chunk_id: str, text: str, **metadata) -> Document:
    return Document(page_content=text, metadata={"chunk_id": chunk_id, **metadata})


def test_bm25_preserves_exact_identifiers_and_metadata() -> None:
    exact = document("exact", "CashReliefConfirmationModal returns HTTP 403", path="Payment.kt")
    other = document("other", "The payment screen renders a checkout form", path="Checkout.kt")

    ranked = BM25Retriever().rank("HTTP 403 CashReliefConfirmationModal", [other, exact])

    assert ranked[0] is exact
    assert exact.metadata["lexical_score"] > 0


def test_rrf_fuses_independent_channels() -> None:
    lexical = document("lexical", "exact PR-1842")
    dense = document("dense", "semantic deployment failure")
    shared = document("shared", "PR-1842 deployment failure")

    fused = ReciprocalRankFusion(k=10).fuse([shared, lexical], [shared, dense], limit=3)

    assert [item.metadata["chunk_id"] for item in fused] == ["shared", "lexical", "dense"]
    assert all(item.metadata["retrieval_channel"] == "hybrid" for item in fused)


def test_rrf_preserves_exact_anchor_metadata_from_dense_duplicate() -> None:
    lexical = document("registry", "POS family (1xx)", lexical_score=4.0)
    exact = document(
        "registry",
        "POS family (1xx)",
        identifier_anchor=True,
        identifier_anchor_score=42.0,
    )

    fused = ReciprocalRankFusion().fuse([lexical], [exact], limit=1)

    assert fused[0].metadata["identifier_anchor"] is True
    assert fused[0].metadata["identifier_anchor_score"] == 42.0


def test_duplicate_candidate_bodies_consume_one_reranking_slot() -> None:
    preferred = document("preferred", "@Composable", content_hash="same", reference="POS.kt")
    duplicate = document("duplicate", "@Composable", content_hash="same", reference="BOT.kt")
    distinct = document("distinct", "fun checkout()", content_hash="other")

    result = deduplicate_candidate_bodies([preferred, duplicate, distinct])

    assert result == [preferred, distinct]
    assert preferred.metadata["duplicate_references"] == ["BOT.kt"]


def test_authorization_filter_fails_closed_and_excludes_cross_project_documents() -> None:
    allowed = document("allowed", "POS evidence", project_id="DEMO", access_policy_id="project:DEMO")
    unauthorized = document("other", "BOT evidence", project_id="AAOS", access_policy_id="project:AAOS")

    result = validate_authorized_candidates(
        [allowed, unauthorized], project_id="DEMO", access_policy_ids=["project:DEMO"]
    )

    assert result == [allowed]
    with pytest.raises(PermissionError):
        validate_authorized_candidates([allowed], project_id="DEMO", access_policy_ids=[])


def test_context_evaluator_reports_no_results_and_sufficient_context() -> None:
    evaluator = HeuristicContextEvaluator()
    empty = evaluator.evaluate("What failed?", [])
    sufficient = evaluator.evaluate(
        "What failed?",
        [document("one", "The build failed", rerank_score=0.91)],
    )

    assert empty.failure_reason == "NO_RESULTS"
    assert empty.retry_recommended is True
    assert sufficient.quality == "SUFFICIENT"
    assert sufficient.retry_recommended is False
