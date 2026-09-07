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
