"""An elliptical "and X?" was being treated as a standalone question, so retrieval
ran on a bare noun with no verb and the router could not pick a source scope."""

import pytest

from app.workflow_support.conversation import (
    _complete_explicit_question,
    _contextual_subtopic_followup,
    _conversation_resolution_decision,
    _conversation_resolution_needed,
    _conversation_subject,
)


def test_and_noun_is_a_followup():
    assert _conversation_resolution_needed("and bot ?") is True


def test_spanish_elliptical_conjunction_is_a_followup():
    assert _conversation_resolution_needed("y bot?") is True


def test_bare_conjunction_with_interrogative_is_a_followup():
    assert _conversation_resolution_needed("and why?") is True


def test_full_question_opening_with_a_conjunction_stays_standalone():
    assert (
        _conversation_resolution_needed("and how does the payment gateway retry?")
        is False
    )


def test_noun_without_a_conjunction_stays_standalone():
    assert _conversation_resolution_needed("bot?") is False


def test_non_vocabulary_token_is_a_followup_when_vocabulary_is_supplied():
    assert _conversation_resolution_decision("now?", ("pos", "bot")) == (
        True,
        "NON_VOCABULARY_SUBJECT",
    )


def test_real_corpus_term_stays_an_explicit_subject():
    assert _conversation_resolution_decision("bot?", ("pos", "bot")) == (
        False,
        "EXPLICIT_SUBJECT",
    )


def test_omitted_vocabulary_preserves_the_existing_decision():
    assert _conversation_resolution_decision("now?") == (False, "EXPLICIT_SUBJECT")


def test_short_verb_ellipsis_is_a_followup_without_a_new_subject():
    question = "I need for POS application"

    assert _conversation_subject(question) == ""
    assert _conversation_resolution_needed(question) is True


@pytest.mark.parametrize(
    ("question", "previous_answer"),
    [
        (
            "Backend of Trade (BOT) flow?",
            "Cash relief can be requested by the Backend of Trade (BOT).",
        ),
        ("cash relief process?", "The POS supports a cash relief operation."),
        ("BOT recovery sequence?", "A BOT recovery plan can contain reliefs."),
        ("flujo de BOT?", "El BOT puede solicitar un alivio de efectivo."),
    ],
)
def test_named_fragment_from_previous_answer_is_a_contextual_subtopic(
    question: str, previous_answer: str
) -> None:
    assert _contextual_subtopic_followup(
        question, [("assistant", previous_answer)]
    )


@pytest.mark.parametrize(
    ("question", "history"),
    [
        ("Backend of Trade (BOT) flow?", []),
        (
            "Backend of Trade (BOT) flow?",
            [("assistant", "The previous answer discussed customer payments.")],
        ),
        (
            "How does the BOT authentication flow work?",
            [("assistant", "BOT can request a cash relief.")],
        ),
        (
            "BOT flow",
            [("assistant", "BOT can request a cash relief.")],
        ),
        (
            "flow?",
            [("assistant", "BOT can request a cash relief.")],
        ),
        (
            "payment workflow?",
            [("user", "Tell me about the payment workflow")],
        ),
    ],
)
def test_named_fragment_does_not_borrow_unrelated_or_unavailable_context(
    question: str, history: list[tuple[str, str]]
) -> None:
    assert not _contextual_subtopic_followup(question, history)


@pytest.mark.parametrize(
    "question",
    [
        "How does a newly named subsystem work?",
        "What is an unindexed service?",
        "Where is a different gateway implemented?",
        "Explain a newly named subsystem architecture",
        "Describe another service contract",
    ],
)
def test_complete_new_topic_is_standalone_even_when_not_in_vocabulary(
    question: str,
) -> None:
    assert _complete_explicit_question(question)
    assert _conversation_resolution_decision(question, ("known-topic",)) == (
        False,
        "EXPLICIT_SUBJECT",
    )


@pytest.mark.parametrize(
    "question",
    [
        "How does it work?",
        "What are its prerequisites?",
        "Explain more",
        "Describe that flow",
    ],
)
def test_referential_or_predicateless_turn_is_not_a_complete_new_topic(
    question: str,
) -> None:
    assert not _complete_explicit_question(question)
