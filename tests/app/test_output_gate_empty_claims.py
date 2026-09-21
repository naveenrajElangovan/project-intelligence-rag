"""An answer with nothing to check must not be treated as a failed check."""

from langchain_core.documents import Document

from app.grounding_contract import resolve_request, validate_output
from app.llm import GroundedAnswer
from app.workflow_support.answer_structure import material_claims


def _documents() -> list[Document]:
    return [
        Document(
            page_content="The POS accepts card payments.",
            metadata={
                "access_policy_id": "project:T2.0",
                "source_type": "PAGE",
                "source_id": "page:1",
                "source_version": "v1",
            },
        )
    ]


def _validate(answer_text: str):
    answer = GroundedAnswer(answer=answer_text, confidence="HIGH", citations=[1])
    return validate_output(
        resolved_request=resolve_request(
            answer_text,
            intent="DIRECT",
            allowed_source_categories=("PAGE",),
            known_entities=(),
        ),
        documents=_documents(),
        generated=answer,
        semantically_supported=True,
        required_policy="project:T2.0",
    )


def test_an_answer_with_no_material_claim_is_not_a_gate_failure() -> None:
    """The pruning path has no sentence to remove, so this discarded the answer."""

    text = "Card payments."
    assert material_claims(text) == []
    assert _validate(text).failure_reason is None


def test_a_cited_claim_still_passes() -> None:
    assert _validate("The POS accepts card payments [SOURCE 1].").failure_reason is None


def test_an_uncited_material_claim_is_still_rejected() -> None:
    """Removing the emptiness check must not weaken the real support check."""

    text = "The POS accepts card payments and settles nightly."
    assert material_claims(text)
    assert _validate(text).failure_reason == "UNSUPPORTED_CLAIM"
