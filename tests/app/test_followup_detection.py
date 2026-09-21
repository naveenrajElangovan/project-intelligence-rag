"""A request that names its own subject is a new topic, not a follow-up.

The live failure: "Give me the flow for checking a price for leche" was asked in
a conversation whose active subject was BOT. Because "give" was not one of the
eight imperative verbs recognised here, the question fell through to the
vocabulary test, was classed as a follow-up, and inherited BOT -- after which
generation scoped the evidence to BOT and excluded ten documents, including the
POS ones where a price flow would live.
"""

import pytest

from app.workflow_support.conversation import (
    _complete_explicit_question,
    _conversation_resolution_decision,
)


@pytest.mark.parametrize(
    "question",
    (
        "Give me the flow for checking a price for leche",
        "Show me the price check steps",
        "Tell me about the price flow",
        "List all features",
        "I need the reprint flow",
        "Dame el flujo para consultar un precio de leche",
        "Muestrame el flujo de precio",
        "Necesito el flujo de reimpresion",
        "What does POS_START_SHIFT require?",
    ),
)
def test_a_request_that_names_its_subject_is_self_contained(question: str) -> None:
    assert _complete_explicit_question(question) is True


@pytest.mark.parametrize(
    "question",
    (
        "tell me more",
        "give me more details",
        "show me more",
        "tell us more about it",
        "dime mas",
        "describe more",
        "explain that again",
        "yes only the fllow",
        "can you give the same answer in points?",
    ),
)
def test_genuine_follow_ups_still_defer_to_the_conversation(question: str) -> None:
    """The indirect object must not let 'tell me more' read as a fresh topic."""

    assert _complete_explicit_question(question) is False


def test_self_contained_request_does_not_inherit_the_previous_subject() -> None:
    """The end-to-end predicate, with a vocabulary that excludes the subject."""

    vocabulary = ("pos", "bot", "iot")

    needed, reason = _conversation_resolution_decision(
        "Give me the flow for checking a price for leche", vocabulary
    )

    assert needed is False
    assert reason == "EXPLICIT_SUBJECT"


def test_an_elliptical_follow_up_still_resolves_against_the_conversation() -> None:
    vocabulary = ("pos", "bot", "iot")

    needed, _reason = _conversation_resolution_decision("tell me more", vocabulary)

    assert needed is True


@pytest.mark.parametrize(
    "question",
    (
        "what is memory here?",
        "what is memoy here",
        "¿qué es memoria aquí?",
    ),
)
def test_locative_definition_with_its_own_subject_is_standalone(question: str) -> None:
    needed, reason = _conversation_resolution_decision(question)

    assert needed is False
    assert reason == "EXPLICIT_LOCATIVE_SUBJECT"


@pytest.mark.parametrize(
    "question",
    (
        "what is it here?",
        "what happened here?",
        "¿qué pasó aquí?",
    ),
)
def test_locative_reference_without_a_subject_still_requires_context(question: str) -> None:
    assert _conversation_resolution_decision(question)[0] is True


@pytest.mark.parametrize(
    "question",
    (
        "price checking flow for products",
        "flujo de consulta de precios para productos",
        "is there a flow for reprints",
        "hay un flujo para reimpresiones",
    ),
)
def test_non_vocabulary_multiword_topics_are_standalone(question: str) -> None:
    needed, reason = _conversation_resolution_decision(question, ("checkout", "inventory"))

    assert needed is False
    assert reason == "EXPLICIT_SUBJECT"


@pytest.mark.parametrize("question", ("reprints", "reimpresiones"))
def test_one_word_non_vocabulary_fragments_still_inherit_context(question: str) -> None:
    needed, reason = _conversation_resolution_decision(question, ("checkout", "inventory"))

    assert needed is True
    assert reason == "NON_VOCABULARY_SUBJECT"
