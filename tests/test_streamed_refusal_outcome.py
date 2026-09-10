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


def test_untyped_refusal_metadata_does_not_discard_substantive_prose() -> None:
    prose = "Open the product list and select the replenishment action. [SOURCE 1]"

    result = normalize_streamed_answer_outcome(
        prose, AnswerOutcome(outcome="REFUSAL", refusal_reason=None)
    )

    assert result.outcome == "ANSWER"
    assert result.refusal_reason is None


@pytest.mark.parametrize(
    "prose",
    (
        (
            "If the ticket did not print, confirm that the sale finished and do not "
            "charge again. Check power, paper, and the accessible printer connection, "
            "then contact authorized support if reprinting fails. [SOURCE 1]"
        ),
        (
            "Si el ticket no se imprimió, confirma que la venta terminó y no vuelvas "
            "a cobrar. Revisa energía, papel y la conexión accesible de la impresora; "
            "si la reimpresión falla, contacta a soporte autorizado. [SOURCE 1]"
        ),
    ),
)
def test_typed_scope_refusal_cannot_discard_store_procedure(prose: str) -> None:
    result = normalize_streamed_answer_outcome(
        prose,
        AnswerOutcome(
            outcome="REFUSAL", refusal_reason="SOURCE_SCOPE_VIOLATION"
        ),
    )

    assert result.outcome == "ANSWER"
    assert result.refusal_reason is None


@pytest.mark.parametrize(
    "reason",
    ("SOURCE_SCOPE_VIOLATION", "UNVERIFIED_EVIDENCE", "INSUFFICIENT_EVIDENCE"),
)
def test_classifier_metadata_cannot_discard_any_grounded_substantive_answer(
    reason: str,
) -> None:
    prose = (
        "The retrieved procedure requires confirming the visible result before "
        "repeating the operation. [SOURCE 1]"
    )

    result = normalize_streamed_answer_outcome(
        prose, AnswerOutcome(outcome="REFUSAL", refusal_reason=reason)
    )

    assert result == AnswerOutcome(outcome="ANSWER", refusal_reason=None)


def test_scope_metadata_without_scope_language_does_not_invent_an_access_problem() -> None:
    result = normalize_streamed_answer_outcome(
        "I cannot answer that detail from the available information.",
        AnswerOutcome(
            outcome="REFUSAL", refusal_reason="SOURCE_SCOPE_VIOLATION"
        ),
    )

    assert result.refusal_reason == "INSUFFICIENT_EVIDENCE"


def test_unverified_refusal_language_gets_the_honest_unverified_reason() -> None:
    result = normalize_streamed_answer_outcome(
        "I cannot verify that detail from the indexed documents.",
        AnswerOutcome(
            outcome="REFUSAL", refusal_reason="SOURCE_SCOPE_VIOLATION"
        ),
    )

    assert result.refusal_reason == "UNVERIFIED_EVIDENCE"


def test_untyped_refusal_metadata_infers_reason_from_explicit_refusal() -> None:
    prose = "I cannot provide deployment instructions because this assistant only covers store operation."

    result = normalize_streamed_answer_outcome(
        prose, AnswerOutcome(outcome="REFUSAL", refusal_reason=None)
    )

    assert result.outcome == "REFUSAL"
    assert result.refusal_reason == "SOURCE_SCOPE_VIOLATION"


def test_substantive_spanish_configuration_answer_is_not_a_prose_refusal() -> None:
    prose = (
        "Para cambiar la configuración, selecciona el producto exacto y abre "
        "Edición de impresión por producto."
    )

    result = normalize_streamed_answer_outcome(
        prose, AnswerOutcome(outcome="ANSWER", refusal_reason=None)
    )

    assert result.outcome == "ANSWER"
