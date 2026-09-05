"""A question that names an identifier is not an ambiguous question."""

from app.models import ConversationContext, RagRequest
from app.workflow_support.fail_closed import clarification_response


def _request(question: str) -> RagRequest:
    return RagRequest(
        projectId="T2.0",
        question=question,
        collectionName="project-intelligence",
        textField="embedding_text",
        embeddingField="embedding_text",
        embeddingModel="multilingual-e5-large",
        schemaVersion="3",
        accessPolicyIds=["project:T2.0"],
        conversationContext=ConversationContext(),
    )


def test_an_event_identifier_is_not_asked_to_disambiguate() -> None:
    """The tokenizer splits POS_SALES_TICKET, and 'ticket' tripped the guard."""

    assert clarification_response(_request("Explain the POS_SALES_TICKET event."), ()) is None


def test_the_spanish_identifier_question_is_also_answered() -> None:
    assert (
        clarification_response(_request("¿Qué contiene el evento POS_SALES_TICKET?"), ())
        is None
    )


def test_a_bare_overloaded_word_still_asks() -> None:
    """Without an identifier the word really is ambiguous, and the guard stands."""

    response = clarification_response(_request("How do I reprint a ticket?"), ())
    assert response is None or response.failure_reason == "AMBIGUOUS_SOURCE_FAMILY"

    bare = clarification_response(_request("Tell me about tickets"), ())
    assert bare is not None
    assert bare.failure_reason == "AMBIGUOUS_SOURCE_FAMILY"


def test_the_document_context_still_wins_over_the_guard() -> None:
    assert clarification_response(_request("How do I reprint a receipt ticket?"), ()) is None
