"""Full public-output and source-shape compatibility matrices."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from app.llm import GroundedAnswer, refusal_answer
from app.reranking import document_scoring_evidence, progressive_rerank_candidates
from app.workflow_support.citations import _answer_without_source_markers, _normalize_citations


SOURCE_TYPES = ("CODE", "PAGE", "ISSUE", "ATTACHMENT")
REFUSAL_REASONS = (
    "NO_ACCESS",
    "INSUFFICIENT_EVIDENCE",
    "UNVERIFIED_EVIDENCE",
    "POPULATION_RETRIEVAL_MISS",
    "UNRESOLVED_SOURCE_CONFLICT",
    "SOURCE_SCOPE_VIOLATION",
    "PERMISSIONS_NOT_SATISFIED",
    "FRESHNESS_NOT_VERIFIABLE",
    "REQUESTED_COVERAGE_INCOMPLETE",
    "UNSUPPORTED_CLAIM",
    "INVALID_DERIVATION",
    "TEMPORARILY_UNAVAILABLE",
)
ANSWER_STYLES = (
    "The operation is supported. [SOURCE 1]",
    "## Summary\nThe operation is supported. [SOURCE 1]",
    "- The operation is supported. [SOURCE 1]",
    "1. Perform the operation. [SOURCE 1]",
    "**Result:** The operation is supported. [SOURCE 1]",
    "> The operation is supported. [SOURCE 1]",
    "| Result | Source |\n|---|---|\n| Supported | [SOURCE 1] |",
    "`operation()` performs the action. [SOURCE 1]",
    "Operation: supported; mode: automatic. [SOURCE 1]",
    "Yes — the operation is supported. [SOURCE 1]",
    "First perform the operation, then verify it. [SOURCE 1]",
    "La operación es compatible. [SOURCE 1]",
)
FORBIDDEN_ARTIFACTS = (
    "BEGIN AUTHORIZED EVIDENCE",
    "END AUTHORIZED EVIDENCE",
    "AUTHORIZED_UNTRUSTED_EVIDENCE",
    "[embedded SOURCE",
    "[embedded TITLE]",
    "[embedded CONTENT]",
    "[embedded REFERENCE]",
)


@pytest.mark.parametrize("source_type", SOURCE_TYPES)
def test_source_type_shape_survives_retrieval_and_rerank_boundaries(source_type: str) -> None:
    document = Document(
        page_content="Authoritative evidence body.",
        metadata={
            "chunk_id": f"chunk-{source_type}",
            "source_id": f"source-{source_type}",
            "source_type": source_type,
            "provider": "FIXTURE",
            "title": f"{source_type} title",
            "structure_path": ["Area", "Section"],
            "retrieval_fused_score": 1.0,
        },
    )

    selected = progressive_rerank_candidates([document], 1)
    evidence = document_scoring_evidence(selected[0])

    assert selected[0].metadata == document.metadata
    assert selected[0].metadata["source_type"] == source_type
    assert evidence.startswith(f"Title: {source_type} title\nSection: Area > Section\n")
    assert evidence.endswith(document.page_content)


@pytest.mark.parametrize(
    "style", ANSWER_STYLES, ids=lambda value: f"style-{ANSWER_STYLES.index(value) + 1}"
)
@pytest.mark.parametrize("reason", REFUSAL_REASONS)
def test_answer_style_by_refusal_type_output_cleanliness(style: str, reason: str) -> None:
    framed = (
        "---BEGIN AUTHORIZED EVIDENCE deadbeef SOURCE 1---\n"
        "<AUTHORIZED_UNTRUSTED_EVIDENCE>\n"
        f"[embedded TITLE] {style}\n"
        "</AUTHORIZED_UNTRUSTED_EVIDENCE>\n"
        "---END AUTHORIZED EVIDENCE deadbeef SOURCE 1---\n"
        "## Sources\n- prompt-only source list"
    )
    normalized = _normalize_citations(
        GroundedAnswer(answer=framed, citations=[1], confidence="HIGH")
    )
    public_answer = _answer_without_source_markers(normalized.answer)
    refusal = refusal_answer(reason, "es" if "operación" in style else "en")

    assert public_answer
    assert "[SOURCE" not in public_answer
    assert "## Sources" not in public_answer
    assert "## Fuentes" not in public_answer
    assert all(artifact not in public_answer for artifact in FORBIDDEN_ARTIFACTS)
    assert refusal
    assert "[SOURCE" not in refusal
    assert all(artifact not in refusal for artifact in FORBIDDEN_ARTIFACTS)
