"""A follow-up must reach the evidence that defines what the last answer named.

From the live transcript: "price-checking flow for a product" was answered well
(relevance 0.844, four claims accepted at 0.96-0.99). The two follow-ups that
came next both refused.

  "what is MC,MP here"    -> predicate_reason EXPLICIT_SUBJECT, conversation
                             dropped, retrieval ran on two bare two-letter
                             tokens, twelve weak documents, every claim rejected
  "from the product types" -> resolved as a follow-up, but retrieval returned a
                             single document at relevance 0.111 and the answer
                             scored 0.0249 on answer relevance

The first is a classification bug ("here" is deictic). The second is the deeper
one: a follow-up inherits a subject but not the identifiers the previous answer
introduced.
"""

import pytest

from app.workflow_support.conversation import (
    _complete_explicit_question,
    _conversation_resolution_decision,
    conversation_anchor_terms,
)


VOCABULARY = ("pos", "bot", "iot")

PREVIOUS_ANSWER = (
    "The price-checking flow for a product is governed by the eligibility policy "
    "defined in [BOTFLOW-110], which evaluates type codes, selling prices, and "
    "price change history to determine notification status. Eligibility requires "
    "the product type to be one of MC, MP, IO, TP, or GR."
)
HISTORY = [
    ("user", "price-checking flow for a product"),
    ("assistant", PREVIOUS_ANSWER),
]


@pytest.mark.parametrize(
    "question",
    ("what is MC,MP here", "que es MC, MP aqui", "what did you mention earlier"),
)
def test_a_deictic_reference_is_not_a_self_contained_question(question: str) -> None:
    """'here' points at the previous turn exactly as 'that' does."""

    assert _complete_explicit_question(question) is False
    assert _conversation_resolution_decision(question, VOCABULARY)[0] is True


@pytest.mark.parametrize(
    "question",
    ("what is the price check flow", "Give me the flow for checking a price"),
)
def test_a_standalone_question_is_unaffected(question: str) -> None:
    assert _conversation_resolution_decision(question, VOCABULARY)[0] is False


def test_an_existential_question_should_be_standalone() -> None:
    assert _conversation_resolution_decision(
        "is there a flow for reprints", VOCABULARY
    )[0] is False


def test_anchor_terms_carry_the_codes_the_question_asks_about() -> None:
    terms = conversation_anchor_terms(HISTORY, "what is MC,MP here")

    assert terms[:2] == ("MC", "MP")
    assert "BOTFLOW-110" in terms


def test_a_section_anchor_survives_a_question_with_no_identifiers() -> None:
    """'from the product types' names nothing retrievable on its own."""

    assert conversation_anchor_terms(HISTORY, "from the product types") == (
        "BOTFLOW-110",
    )


def test_codes_the_question_does_not_ask_about_are_not_dragged_in() -> None:
    terms = conversation_anchor_terms(HISTORY, "what is MC here")

    assert "MC" in terms
    assert "MP" not in terms
    assert "GR" not in terms


def test_no_conversation_produces_no_anchors() -> None:
    assert conversation_anchor_terms([], "what is MC,MP here") == ()
    assert conversation_anchor_terms([("user", "hola")], "what is MC here") == ()


def test_anchor_terms_are_bounded() -> None:
    noisy = " ".join(f"CODE-{n}" for n in range(40))
    terms = conversation_anchor_terms([("assistant", noisy)], "what is this", limit=6)

    assert len(terms) <= 6
