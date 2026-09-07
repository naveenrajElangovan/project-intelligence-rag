"""English and Spanish must reach the same decision for the same question.

Several detectors were written as English word lists and never given a Spanish
half, so identical questions took different paths depending on the language they
were asked in. These tests pin the pairs rather than the lists, so adding a term
to one language without the other fails here.
"""

import pytest

from app.grounding import _negation_supported
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
