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
    assert clarification_response(_request("¿Qué contiene el evento POS_SALES_TICKET?"), ()) is None


def test_a_bare_overloaded_word_still_asks() -> None:
    """Without an identifier the word really is ambiguous, and the guard stands."""

    response = clarification_response(_request("How do I reprint a ticket?"), ())
    assert response is None or response.failure_reason == "AMBIGUOUS_SOURCE_FAMILY"

    bare = clarification_response(_request("Tell me about tickets"), ())
    assert bare is not None
    assert bare.failure_reason == "AMBIGUOUS_SOURCE_FAMILY"


def test_the_document_context_still_wins_over_the_guard() -> None:
    assert clarification_response(_request("How do I reprint a receipt ticket?"), ()) is None


def test_explicit_standalone_topic_request_is_not_treated_as_a_followup() -> None:
    assert clarification_response(_request("Tell me about Shrinkage."), ()) is None
    assert clarification_response(_request("Dime sobre Navegación."), ()) is None


def test_ticket_vocabulary_is_documentary_not_an_overloaded_record() -> None:
    assert (
        clarification_response(
            _request("Tell me about ticket and payment vocabulary."),
            (),
            ("PAGE", "CODE", "ISSUE"),
        )
        is None
    )


def test_hyphenated_fictitious_subject_fails_closed_as_a_named_unknown() -> None:
    response = clarification_response(
        _request("What unrecorded owner approved phantom-libraries?"),
        (),
    )

    assert response is not None
    assert response.status == "INSUFFICIENT_EVIDENCE"
    assert response.failure_reason == "EXPLICIT_UNSUPPORTED_PREMISE"


def test_spanish_plural_fictitious_population_fails_closed() -> None:
    for question in (
        "¿Cuáles son todos los comandos imaginarios QZ compatibles?",
        "Enumera todos los miembros inexistentes del protocolo QZ.",
        "¿Qué servicios ficticios QZ están definidos?",
    ):
        response = clarification_response(_request(question), ())
        assert response is not None
        assert response.failure_reason == "EXPLICIT_UNSUPPORTED_PREMISE"
        assert response.refusal_reason == "POPULATION_RETRIEVAL_MISS"
