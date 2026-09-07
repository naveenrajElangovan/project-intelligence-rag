"""The judge's bias controls are mechanics, so they are testable without a model."""

from evaluation.pairwise_judge import (
    LENGTH_TOLERANCE,
    PAIRWISE_SYSTEM_PROMPT,
    PairwiseVerdict,
    aggregate,
    length_ratio,
    presentation_order,
    reconcile,
)


def _pair(case_id: str, first, second, *, baseline="a b c", candidate="a b c", language="en"):
    return reconcile(
        case_id,
        query_language=language,
        baseline_answer=baseline,
        candidate_answer=candidate,
        first_pass=first,
        second_pass=second,
    )


def test_every_pair_is_shown_in_both_orders() -> None:
    for case_id in ("case-1", "case-2", "case-3"):
        assert presentation_order(case_id, swap=False) is not presentation_order(
            case_id, swap=True
        )


def test_presentation_order_is_deterministic() -> None:
    assert presentation_order("case-1", swap=False) == presentation_order(
        "case-1", swap=False
    )


def test_agreement_across_both_orders_is_a_real_verdict() -> None:
    result = _pair("case-1", "RESPONSE_1", "RESPONSE_2")

    # Whichever label the candidate wore, both passes named the same system.
    assert result.outcome in {"BASELINE", "CANDIDATE"}
    assert result.first_pass == result.second_pass
    assert result.position_bias is False


def test_a_judge_that_follows_position_produces_a_tie_and_a_flag() -> None:
    """Both passes picked whatever was shown first: that is position, not quality."""

    result = _pair("case-1", "RESPONSE_1", "RESPONSE_1")

    assert result.outcome == "TIE"
    assert result.position_bias is True


def test_length_ratio_is_orientation_independent() -> None:
    assert length_ratio("one two three four", "one two") == 2.0
    assert length_ratio("one two", "one two three four") == 2.0


def test_a_length_mismatch_is_excluded_from_the_headline_rate() -> None:
    matched = _pair("case-1", "RESPONSE_1", "RESPONSE_2")
    lopsided = _pair(
        "case-2",
        "RESPONSE_1",
        "RESPONSE_2",
        baseline="one two three four five six seven eight nine ten",
        candidate="one two",
    )

    summary = aggregate([matched, lopsided])

    assert lopsided.length_mismatch is True
    assert lopsided.length_ratio > LENGTH_TOLERANCE
    assert summary["pairs"] == 2
    assert summary["comparable_pairs"] == 1
    assert summary["length_mismatch_rate"] == 0.5


def test_a_high_position_bias_rate_disqualifies_the_win_rate() -> None:
    biased = [_pair(f"case-{n}", "RESPONSE_1", "RESPONSE_1") for n in range(4)]
    clean = [_pair("case-9", "RESPONSE_1", "RESPONSE_2")]

    assert aggregate(biased)["verdict_reliability"] == "UNRELIABLE_POSITION_BIAS"
    assert aggregate(clean)["verdict_reliability"] == "OK"


def test_language_split_and_gap_are_reported() -> None:
    rows = [
        _pair("case-1", "RESPONSE_1", "RESPONSE_2", language="en"),
        _pair("case-2", "RESPONSE_1", "RESPONSE_2", language="es"),
    ]

    summary = aggregate(rows)

    assert "en.candidate_win_rate" in summary
    assert "es.candidate_win_rate" in summary
    assert "language_gap.candidate_win_rate" in summary


def test_reasoning_precedes_the_verdict_in_the_schema() -> None:
    """Field order is the chain of thought; a verdict emitted first is a guess."""

    fields = list(PairwiseVerdict.model_fields)

    assert fields.index("reasoning") < fields.index("winner")
    assert fields.index("grounding_winner") < fields.index("winner")


def test_the_rubric_states_the_controls_the_code_enforces() -> None:
    assert "IGNORE LENGTH" in PAIRWISE_SYSTEM_PROMPT
    assert "IGNORE ORDER" in PAIRWISE_SYSTEM_PROMPT
    assert "TIE is a real verdict" in PAIRWISE_SYSTEM_PROMPT
