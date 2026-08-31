"""The prompt must fit the context window by construction, not by luck.

Ollama does not error on an over-long prompt; it discards tokens from the start of
the context, which is exactly where the system instructions live. The visible
symptom is a citation or grounding failure, so the only safe place to catch it is
configuration and preflight.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.workflow_support.conversation import _bounded_history


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, environment="development", **overrides)


def test_context_window_default_is_not_the_old_ceiling() -> None:
    settings = _settings()
    assert settings.ollama_context_tokens >= 32_768


def test_evidence_plus_reserved_tokens_must_fit_the_window() -> None:
    with pytest.raises(ValidationError) as error:
        _settings(ollama_context_tokens=8_192, max_evidence_tokens=16_000)
    assert "does not fit the context window" in str(error.value)


def test_a_window_above_the_model_native_limit_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _settings(ollama_context_tokens=300_000)


def test_penalties_default_to_neutral_so_citation_is_not_discouraged() -> None:
    settings = _settings()
    assert settings.ollama_presence_penalty == 0.0
    assert settings.ollama_repeat_penalty == 1.0


def test_chat_modes_select_different_ollama_models() -> None:
    settings = _settings()
    assert settings.model_for_profile("budget") == settings.ollama_planner_model
    assert settings.model_for_profile("standard") == settings.ollama_model
    assert settings.model_for_profile("complex") == settings.ollama_model


def test_conversation_history_is_trimmed_to_its_budget() -> None:
    history = [("user", "a" * 9_000), ("assistant", "b" * 9_000), ("user", "c" * 60)]
    bounded = _bounded_history(history, 200)
    joined = "".join(content for _role, content in bounded)
    assert len(joined.encode("utf-8")) <= 200 * 3
    # The newest turn is the one that resolves a follow-up, so it must survive.
    assert bounded[-1][1].startswith("c")


def test_a_zero_history_budget_drops_history_entirely() -> None:
    assert _bounded_history([("user", "anything")], 0) == []


def test_history_within_budget_is_untouched() -> None:
    history = [("user", "short question"), ("assistant", "short answer")]
    assert _bounded_history(history, 2_000) == history
