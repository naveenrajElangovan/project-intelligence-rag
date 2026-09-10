"""An answer must address the question, not merely cite its evidence correctly.

The live failure: a follow-up produced a MEDIUM-confidence answer about keyboard
shortcuts (AppShortcuts, ProductsShortcuts, GlobalKeyboardHandler) for a question
about the price-checking flow. Every sentence was supported by a retrieved chunk,
so grounding passed it -- grounding calls `del question` and judges support only.
"""

import asyncio

from app.config import Settings
from app.grounding import LocalCitationGroundingVerifier


QUESTION = "Give me the flow for checking a price for leche"
OFF_TOPIC = (
    "The bot utilizes specific keyboard shortcuts implemented in code files such "
    "as `AppShortcuts`, `ProductsShortcuts`, and `GlobalKeyboardHandler`. "
    "[SOURCE 1]"
)
ON_TOPIC = "The price check flow starts at the product lookup screen. [SOURCE 1]"


class StubbedScoreVerifier(LocalCitationGroundingVerifier):
    """Real logic, fixed cross-encoder output, no model load."""

    def __init__(self, settings: Settings, score: float) -> None:
        super().__init__(settings)
        self._stub_score = score
        self.scored_pairs: list[tuple[str, str]] = []

    async def _ensure_scores(self, pairs, *, batch_size=None) -> None:
        for pair in pairs:
            self.scored_pairs.append(pair)
            self._pair_score_cache[pair] = self._stub_score


def _settings() -> Settings:
    return Settings(_env_file=None, environment="development")


def _check(answer: str, score: float, threshold: float = 0.10):
    verifier = StubbedScoreVerifier(_settings(), score)
    return verifier, asyncio.run(
        verifier.answer_addresses_question(QUESTION, answer, threshold=threshold)
    )


def test_off_topic_answer_is_rejected_however_well_cited() -> None:
    _verifier, (addresses, score) = _check(OFF_TOPIC, 0.004)

    assert addresses is False
    assert score == 0.004


def test_on_topic_answer_passes() -> None:
    _verifier, (addresses, score) = _check(ON_TOPIC, 0.83)

    assert addresses is True
    assert score == 0.83


def test_the_bar_is_the_configured_threshold() -> None:
    assert _check(ON_TOPIC, 0.10)[1][0] is True
    assert _check(ON_TOPIC, 0.0999)[1][0] is False


def test_citation_markers_are_not_scored_as_content() -> None:
    verifier, _result = _check(ON_TOPIC, 0.5)

    scored_question, scored_answer = verifier.scored_pairs[0]
    assert scored_question == QUESTION
    assert "[SOURCE" not in scored_answer


def test_markdown_tables_are_linearized_before_relevance_scoring() -> None:
    table = (
        "| Attribute | Value | Source |\n"
        "|---|---|---|\n"
        "| identifier | entry-17 | [SOURCE 1] |"
    )
    verifier, _result = _check(table, 0.5)

    _scored_question, scored_answer = verifier.scored_pairs[0]
    assert "identifier" in scored_answer
    assert "Value: entry-17" in scored_answer
    assert "|" not in scored_answer


def test_an_empty_answer_defers_rather_than_inventing_a_refusal() -> None:
    _verifier, (addresses, score) = _check("   ", 0.0)

    assert addresses is True
    assert score == 1.0


def test_threshold_default_is_declared_in_settings() -> None:
    assert _settings().answer_relevance_threshold == 0.10
