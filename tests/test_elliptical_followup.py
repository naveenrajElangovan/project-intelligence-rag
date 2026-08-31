"""An elliptical "and X?" was being treated as a standalone question, so retrieval
ran on a bare noun with no verb and the router could not pick a source scope."""

from app.workflow_support.conversation import (
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


def test_short_verb_ellipsis_is_a_followup_without_a_new_subject():
    question = "I need for POS application"

    assert _conversation_subject(question) == ""
    assert _conversation_resolution_needed(question) is True
