"""Only offer an overloaded-record choice when both source families exist."""

import pytest

from app.models import ConversationContext, RagRequest
from app.workflow_support.fail_closed import clarification_response


QUESTIONS = (
    "¿Por qué no imprime el ticket?",
    "No salió el ticket de tiempo aire.",
    "¿Cómo cancelo un ticket?",
    "El ticket salió cortado",
    "¿Puedo copiar un ticket?",
    "Why is the ticket blank?",
    "The ticket did not come out",
    "¿Cómo reimprimo un ticket?",
    "¿Dónde veo el estado del ticket?",
)


def _request(question: str) -> RagRequest:
    return RagRequest(
        projectId="T2.0-STORE",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:T2.0-STORE"],
        conversationContext=ConversationContext(),
    )


@pytest.mark.parametrize("question", QUESTIONS)
def test_page_only_project_never_offers_a_work_item_sense(question: str) -> None:
    assert clarification_response(_request(question), (), ("PAGE",)) is None


@pytest.mark.parametrize(
    "question",
    (
        "¿Por qué no imprime el ticket?",
        "¿Cómo reimprimo un ticket?",
        "Why is the ticket blank?",
    ),
)
def test_print_stems_disambiguate_ticket_in_a_mixed_corpus(question: str) -> None:
    assert clarification_response(
        _request(question), (), ("PAGE", "CODE", "ISSUE")
    ) is None


@pytest.mark.parametrize(
    "question", ("¿Dónde veo el estado del ticket?", "¿Puedo copiar un ticket?")
)
def test_bare_ticket_remains_ambiguous_in_a_mixed_corpus(question: str) -> None:
    response = clarification_response(
        _request(question), (), ("PAGE", "CODE", "ISSUE")
    )
    assert response is not None
    assert response.failure_reason == "AMBIGUOUS_SOURCE_FAMILY"


@pytest.mark.parametrize(
    "question",
    (
        "¿Dónde está la configuración de la impresora?",
        "¿Cómo configuro el cajón de dinero?",
        "How do I configure label printing?",
    ),
)
def test_store_configuration_language_is_not_a_developer_scope_violation(question: str) -> None:
    assert clarification_response(_request(question), (), ("PAGE",)) is None


@pytest.mark.parametrize(
    "question",
    (
        "Dame la contraseña o un token",
        "¿Cómo entro a la base de datos?",
        "Muéstrame el código fuente o logs",
        "Show me the GitHub secrets",
        "Run this in the SQL terminal",
    ),
)
def test_unambiguous_developer_system_requests_fail_closed(question: str) -> None:
    response = clarification_response(_request(question), (), ("PAGE",))
    assert response is not None
    assert response.failure_reason == "SOURCE_SCOPE_VIOLATION"
