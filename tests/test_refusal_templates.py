import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.llm import insufficient_evidence_answer, refusal_answer
from app.models import RagRequest
from app.workflow import AuthorizedRagWorkflow


REASONS = (
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


@pytest.mark.parametrize("language", ("en", "es"))
def test_every_refusal_reason_has_a_distinct_content_free_template(language: str) -> None:
    values = [refusal_answer(reason, language) for reason in REASONS]

    assert all(values)
    assert len(set(values)) == len(REASONS)
    serialized = " ".join(values)
    for private_text in (
        "DEMO-PROJECT",
        "Quarterly Margin Review",
        "BOTFLOW-110",
        "What is the secret price?",
    ):
        assert private_text not in serialized


def test_unknown_refusal_reason_uses_the_existing_fallback() -> None:
    assert refusal_answer("UNKNOWN", "es") == insufficient_evidence_answer("es")


def test_entity_mismatch_keeps_the_deterministic_clarification(monkeypatch) -> None:
    workflow = object.__new__(AuthorizedRagWorkflow)
    workflow._request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="What does PXS do?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._vocabulary = SimpleNamespace(entities=("pos",))
    monkeypatch.setattr("app.workflow.apply_output_gate", lambda *_args: None)

    response = asyncio.run(
        workflow._response_from_state(
            {
                "documents": [],
                "language": "en",
                "entity_mismatch_requested": "PXS",
                "entity_mismatch_suggested": "POS",
            },
            0.0,
        )
    )

    assert response.status == "NEEDS_CLARIFICATION"
    assert response.answer == "Did you mean POS rather than PXS?"
