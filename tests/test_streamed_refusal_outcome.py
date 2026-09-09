import pytest

from app.llm import AnswerOutcome, normalize_streamed_answer_outcome


@pytest.mark.parametrize(
    "prose",
    (
        "The assistant must decline requests to change configuration because it only covers visible store operation.",
        "I cannot provide installation or deployment instructions because this assistant is restricted to store operation.",
        "No puedo instalar ni desplegar porque el asistente solo cubre la operación visible.",
    ),
)
def test_explicit_streamed_prose_refusal_overrides_answer_metadata(prose: str) -> None:
    result = normalize_streamed_answer_outcome(
        prose, AnswerOutcome(outcome="ANSWER", refusal_reason=None)
    )

    assert result.outcome == "REFUSAL"
    assert result.refusal_reason == "SOURCE_SCOPE_VIOLATION"


def test_operational_warning_is_not_misclassified_as_a_refusal() -> None:
    prose = (
        "Verify the payment status before continuing. Do not repeat the payment while "
        "the result is ambiguous."
    )

    result = normalize_streamed_answer_outcome(
        prose, AnswerOutcome(outcome="ANSWER", refusal_reason=None)
    )

    assert result.outcome == "ANSWER"
    assert result.refusal_reason is None


def test_substantive_spanish_configuration_answer_is_not_a_prose_refusal() -> None:
    prose = (
        "Para cambiar la configuración, selecciona el producto exacto y abre "
        "Edición de impresión por producto."
    )

    result = normalize_streamed_answer_outcome(
        prose, AnswerOutcome(outcome="ANSWER", refusal_reason=None)
    )

    assert result.outcome == "ANSWER"
