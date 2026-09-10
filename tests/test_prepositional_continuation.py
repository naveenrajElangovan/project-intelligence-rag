"""A turn opening with a bare preposition has no predicate of its own."""

import asyncio

import pytest

from app.config import Settings
from app.models import ConversationContext, ConversationMessage, RagRequest
from app.workflow import AuthorizedRagWorkflow
from app.workflow_support.fail_closed import clarification_response
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


@pytest.mark.parametrize(
    "question",
    (
        "¿Qué debo revisar antes del cierre de caja?",
        "¿Qué debo hacer previamente al cierre de día?",
    ),
)
def test_temporal_store_procedure_is_not_an_anaphoric_followup(question: str) -> None:
    assert _conversation_resolution_decision(question, VOCABULARY)[0] is False
    assert clarification_response(_request(question), (), ("PAGE",)) is None


def test_the_reason_code_is_content_free() -> None:
    assert _conversation_resolution_decision(
        "from the product types", VOCABULARY
    )[1] == "LEADING_FRAGMENT_CONTINUATION"


FIRST_TURN_FRAGMENTS = (
    "sobre las reimpresiones",
    "sobre el cierre de caja",
    "de los tipos de producto",
    "para el flujo de precios",
    "sobre el ticket",
    "acerca del inventario",
    "con el departamento de finanzas",
    "about the reprints",
    "from the product types",
    "regarding the cash drawer",
)


def _request(question: str, *, with_history: bool = False) -> RagRequest:
    return RagRequest(
        projectId="T2.0-STORE",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:T2.0-STORE"],
        conversationContext=ConversationContext(),
        conversationHistory=(
            [ConversationMessage(role="user", content="Tell me about POS closure")]
            if with_history
            else []
        ),
    )


@pytest.mark.parametrize("question", FIRST_TURN_FRAGMENTS)
def test_leading_fragment_is_standalone_when_there_is_no_prior_turn(
    question: str,
) -> None:
    assert clarification_response(_request(question), (), ("PAGE",)) is None


def test_leading_fragment_predicate_still_marks_a_real_followup() -> None:
    needed, reason = _conversation_resolution_decision(
        "sobre el cierre de caja", VOCABULARY
    )
    assert needed is True
    assert reason == "LEADING_FRAGMENT_CONTINUATION"
    assert clarification_response(
        _request("sobre el cierre de caja", with_history=True), (), ("PAGE",)
    ) is None


@pytest.mark.parametrize(
    ("question", "language", "expected"),
    (
        (
            "sobre el cierre de caja",
            "es",
            "¿Cuál es el procedimiento sobre el cierre de caja?",
        ),
        (
            "regarding the cash drawer",
            "en",
            "What is the procedure regarding the cash drawer?",
        ),
    ),
)
def test_first_turn_leading_fragment_becomes_a_standalone_question(
    question: str, language: str, expected: str
) -> None:
    request = _request(question)
    workflow = AuthorizedRagWorkflow.__new__(AuthorizedRagWorkflow)
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")

    resolved = asyncio.run(workflow._resolve_conversation_question(question, language))

    assert resolved == expected
