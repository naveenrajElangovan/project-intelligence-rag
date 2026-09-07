"""A turn opening with a bare preposition has no predicate of its own."""

import pytest

from app.workflow_support.conversation import _conversation_resolution_decision

VOCABULARY = ("pos", "bot", "iot")


@pytest.mark.parametrize(
    "question",
    (
        "from the product types",
        "de los tipos de producto",
        "para el flujo de precios",
        "about the reprints",
        "sobre las reimpresiones",
        "for leche",
        "con el departamento de finanzas",
        "según el manual de compras",
        "From the product types.",
        "¿de los tipos de producto?",
    ),
)
def test_a_preposition_initial_fragment_continues_the_previous_turn(
    question: str,
) -> None:
    assert _conversation_resolution_decision(question, VOCABULARY)[0] is True


@pytest.mark.parametrize(
    "question",
    (
        "from the product types, what is MC?",
        "de acuerdo con la politica de compras, cual es el limite?",
        "for the price check flow what does the POS require",
        "sobre el flujo de precios de leche en las tiendas 3B",
    ),
)
def test_a_fragment_with_its_own_predicate_stays_standalone(question: str) -> None:
    assert _conversation_resolution_decision(question, VOCABULARY)[0] is False


def test_the_reason_code_is_content_free() -> None:
    assert _conversation_resolution_decision(
        "from the product types", VOCABULARY
    )[1] == "PREPOSITIONAL_CONTINUATION"
