import math

import pytest

from app.reranking import normalized_relevance_score


def test_score_normalization_is_monotonic_across_the_full_logit_range() -> None:
    logits = (-1000.0, -100.0, -10.0, -1.0, -1e-9, 0.0, 1e-9, 1.0, 10.0, 100.0, 1000.0)
    scores = [normalized_relevance_score(value) for value in logits]

    assert scores == sorted(scores)
    assert scores[4] < scores[5] < scores[6]
    assert all(0.0 <= score <= 1.0 and math.isfinite(score) for score in scores)


def test_score_normalization_has_no_discontinuity_at_zero_or_one() -> None:
    epsilon = 1e-9
    assert normalized_relevance_score(-epsilon) < normalized_relevance_score(0.0)
    assert normalized_relevance_score(0.0) < normalized_relevance_score(epsilon)
    assert normalized_relevance_score(1.0 - epsilon) < normalized_relevance_score(1.0)
    assert normalized_relevance_score(1.0) < normalized_relevance_score(1.0 + epsilon)


def test_nan_score_is_rejected() -> None:
    with pytest.raises(ValueError, match="NaN"):
        normalized_relevance_score(float("nan"))
