"""English and Spanish must reach the same decision for the same question.

Several detectors were written as English word lists and never given a Spanish
half, so identical questions took different paths depending on the language they
were asked in. These tests pin the pairs rather than the lists, so adding a term
to one language without the other fails here.
"""

import pytest

from app.grounding import _negation_supported
from app.workflow_nodes.planning import (
    _entity_attribute_value_requested,
    _implementation_flow_requested,
    _single_record_details_requested,
    _structured_inventory_requested,
)
from app.workflow_support.citations import _overview_style_repair_needed
from app.workflow_support.completeness import _answer_requirements, _code_output_requested
from app.workflow_support.conversation import _conversation_resolution_decision
from app.workflow_support.inventory_intent import is_inventory_question


VOCABULARY = ("pos", "bot", "iot")


@pytest.mark.parametrize(
    ("english", "spanish"),
    (
        ("List all events", "Lista todos los eventos"),
        ("What are the supported statuses", "Cuales son los estados soportados"),
        ("Show me every configured field", "Muestrame cada campo configurado"),
        ("What events exist", "Que eventos existen"),
        ("the full event catalog", "el catalogo completo de eventos"),
    ),
)
def test_inventory_intent_is_symmetric(english: str, spanish: str) -> None:
    assert is_inventory_question(english) is True
    assert is_inventory_question(spanish) is True


@pytest.mark.parametrize(
    ("english", "spanish"),
    (
        ("tell me more", "dime más"),
        ("tell me more", "dime mas"),
        ("what else", "qué más"),
        ("what else", "que mas"),
        ("continue", "continúa"),
        ("continue", "continua"),
    ),
)
def test_follow_up_detection_is_symmetric(english: str, spanish: str) -> None:
    """Accented and unaccented Spanish must behave like the English original."""

    assert _conversation_resolution_decision(english, VOCABULARY)[0] is True
    assert _conversation_resolution_decision(spanish, VOCABULARY)[0] is True


@pytest.mark.parametrize(
    ("english", "spanish"),
    (
        (
            "Give me the flow for checking a price",
            "Dame el flujo para consultar un precio",
        ),
        ("Show me the reprint steps", "Muestrame los pasos de reimpresion"),
    ),
)
def test_self_contained_requests_are_symmetric(english: str, spanish: str) -> None:
    assert _conversation_resolution_decision(english, VOCABULARY)[0] is False
    assert _conversation_resolution_decision(spanish, VOCABULARY)[0] is False


def test_negation_is_recognised_in_both_languages() -> None:
    assert _negation_supported(
        "It applies without tax.", "The total is computed without tax."
    ) is True
    assert _negation_supported(
        "Se aplica sin impuestos.", "El total se calcula sin impuestos."
    ) is True


def test_a_negated_claim_without_negated_evidence_is_still_rejected() -> None:
    """The guard must keep working, not just stop firing on Spanish."""

    assert _negation_supported(
        "It applies without tax.", "The total includes tax."
    ) is False
    assert _negation_supported(
        "Se aplica sin impuestos.", "El total incluye impuestos."
    ) is False


def test_a_claim_with_no_negation_is_unaffected() -> None:
    assert _negation_supported("El flujo registra el pago.", "Cualquier cosa.") is True


@pytest.mark.parametrize(
    ("english_question", "spanish_question", "english_answer", "spanish_answer", "expected"),
    (
        (
            "Tell me about the checkout service",
            "Háblame del servicio de cobro",
            "Its maturity is draft [SOURCE 1].",
            "Su madurez es borrador [SOURCE 1].",
            True,
        ),
        (
            "How many files are in the checkout service?",
            "¿Cuántos archivos hay en el servicio de cobro?",
            "It has 12 files [SOURCE 1].",
            "Tiene 12 archivos [SOURCE 1].",
            False,
        ),
        (
            "Tell me about the checkout service",
            "Háblame del servicio de cobro",
            "It is implemented by the following modules [SOURCE 1].",
            "Está implementado por los siguientes módulos [SOURCE 1].",
            True,
        ),
    ),
)
def test_overview_citation_guard_is_symmetric(
    english_question: str,
    spanish_question: str,
    english_answer: str,
    spanish_answer: str,
    expected: bool,
) -> None:
    assert _overview_style_repair_needed(english_question, english_answer) is expected
    assert _overview_style_repair_needed(spanish_question, spanish_answer) is expected


@pytest.mark.parametrize(
    ("detector", "english", "spanish"),
    (
        (
            _implementation_flow_requested,
            "How is login implemented?",
            "¿Cómo se implementa el inicio de sesión?",
        ),
        (
            _structured_inventory_requested,
            "List the complete event catalog",
            "Lista el catálogo completo de eventos",
        ),
        (
            _single_record_details_requested,
            "Show one complete example record",
            "Muestra un registro de ejemplo completo",
        ),
        (
            _entity_attribute_value_requested,
            "How is CHECKOUT_EVENT status assigned?",
            "¿Cómo se asigna el estado de CHECKOUT_EVENT?",
        ),
        (
            _code_output_requested,
            "Show the implementation code",
            "Muestra el código de implementación",
        ),
    ),
)
def test_query_shape_detectors_are_symmetric(detector, english: str, spanish: str) -> None:
    assert detector(english) is True
    assert detector(spanish) is True


def test_enumerated_screen_requirements_are_symmetric() -> None:
    english = _answer_requirements("Which login, payment, and closing screen types?")
    spanish = _answer_requirements(
        "¿Cuáles son los tipos de pantalla acceso, pago y cierre?"
    )

    assert english == ("term:login", "term:payment", "term:closing")
    assert spanish == ("term:acceso", "term:pago", "term:cierre")
