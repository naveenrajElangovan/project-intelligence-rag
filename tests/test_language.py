"""English/Spanish resolution and deterministic query autocorrection."""

import pytest

from app.workflow_support.language import (
    DEFAULT_RESPONSE_LANGUAGE,
    SUPPORTED_LANGUAGES,
    autocorrect_question,
    correction_count,
    detect_query_language,
    is_unclassifiable,
    language_name,
    latest_supported_user_language,
    resolve_conversation_response_language,
    resolve_response_language,
)


MIXED_TYPO_QUESTION = "wat is BOT como functiona?"


def test_response_language_is_never_a_third_language() -> None:
    """The reported regression: a Spanglish typo answered in Dutch."""

    for question in (
        MIXED_TYPO_QUESTION,
        "BOT",
        "wat is de status",
        "",
        "??? ???",
    ):
        assert resolve_response_language(question) in SUPPORTED_LANGUAGES


def test_language_name_never_delegates_the_choice_to_the_model() -> None:
    assert language_name("en") == "English"
    assert language_name("es") == "Spanish"
    assert language_name("mixed") in {"English", "Spanish"}
    assert language_name("nl") in {"English", "Spanish"}


def test_typo_no_longer_zeroes_both_language_counters() -> None:
    """'functiona' used to score 0/0 and fall through to the model's guess."""

    assert autocorrect_question(MIXED_TYPO_QUESTION) == "what is BOT como funciona?"
    # Genuinely bilingual once repaired ("what is" against "como funciona"), so
    # the classifier says so instead of guessing -- and resolution, not the
    # model, decides which supported language the answer comes back in.
    assert detect_query_language(MIXED_TYPO_QUESTION) == "mixed"
    assert resolve_response_language(MIXED_TYPO_QUESTION) == "es"
    assert resolve_response_language(MIXED_TYPO_QUESTION, previous="en") == "en"


@pytest.mark.parametrize(
    ("question", "corrected"),
    (
        ("whta is teh status of the sprint", "what is the status of the sprint"),
        ("cual es el esatdo de la cuenta", "cual es el estado de la cuenta"),
        ("wat is BOT como functiona?", "what is BOT como funciona?"),
    ),
)
def test_autocorrect_repairs_question_words(question: str, corrected: str) -> None:
    assert autocorrect_question(question) == corrected


@pytest.mark.parametrize(
    "question",
    (
        "status of POS_RECEIPT_v2, T2-431 and app.main.py",
        "How does the reprint flow work in Tiendas3B?",
        "que pasa con las ventas y los pedidos del cliente",
        "show me the last user role",
        "dame los detalle de la reimpresion",
        "el bot",
    ),
)
def test_autocorrect_leaves_domain_language_alone(question: str) -> None:
    """Identifiers, acronyms, inflections and real words are never rewritten."""

    assert autocorrect_question(question) == question
    assert correction_count(question) == 0


def test_project_entities_are_protected_from_correction() -> None:
    assert autocorrect_question("como funciona bot", vocabulary=("bot",)) == (
        "como funciona bot"
    )


def test_detection_regressions_hold() -> None:
    assert detect_query_language("Tell me about POS") == "en"
    assert detect_query_language("List all features") == "en"
    assert detect_query_language("¿Cómo funciona el proceso de reimpresión?") == "es"
    assert detect_query_language("what is the status of T2-431") == "en"


def test_unclassifiable_falls_back_to_the_configured_default() -> None:
    assert is_unclassifiable("BOT") is True
    assert resolve_response_language("BOT") == DEFAULT_RESPONSE_LANGUAGE
    assert resolve_response_language("BOT", default="en") == "en"
    assert resolve_response_language("BOT", previous="en") == "en"
    assert resolve_response_language("Tell me about POS", previous="es") == "en"


def test_ambiguous_english_followup_inherits_previous_user_language() -> None:
    history = [
        ("user", "Give me the flow for checking a price for leche"),
        ("assistant", "No se encontraron detalles suficientes."),
    ]
    assert latest_supported_user_language(history) == "en"
    assert (
        resolve_conversation_response_language(
            "Yes price check flow", history, default="es"
        )
        == "en"
    )


def test_ambiguous_spanish_followup_inherits_spanish_but_explicit_english_wins() -> None:
    history = [("user", "Explícame el flujo para verificar un precio")]
    assert resolve_conversation_response_language("Sí, ese flujo", history) == "es"
    assert (
        resolve_conversation_response_language("Explain that flow", history) == "en"
    )


def test_assistant_language_is_not_used_as_conversation_language() -> None:
    history = [("assistant", "Respuesta en español")]
    assert latest_supported_user_language(history) is None
    assert resolve_conversation_response_language("BOT", history, default="en") == "en"


def test_correction_is_deterministic() -> None:
    first = autocorrect_question(MIXED_TYPO_QUESTION)
    for _ in range(25):
        assert autocorrect_question(MIXED_TYPO_QUESTION) == first
