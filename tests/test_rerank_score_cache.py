"""A cross-encoder score is deterministic, so it should be computed once."""

import app.reranking as reranking


def _clear() -> None:
    with reranking._SCORE_CACHE_LOCK:
        reranking._SCORE_CACHE.clear()


def test_a_repeated_pair_is_not_scored_twice() -> None:
    _clear()
    calls: list[list[tuple[str, str]]] = []

    def compute(pairs):
        calls.append(list(pairs))
        return [float(len(evidence)) for _query, evidence in pairs]

    pairs = [("q", "alpha"), ("q", "beta")]
    first = reranking.cached_scores("model", 1024, pairs, compute)
    second = reranking.cached_scores("model", 1024, pairs, compute)

    assert first == second == [5.0, 4.0]
    assert len(calls) == 1, "the second call must be served entirely from cache"


def test_only_the_unknown_pairs_are_computed() -> None:
    _clear()
    computed: list[tuple[str, str]] = []

    def compute(pairs):
        computed.extend(pairs)
        return [1.0 for _ in pairs]

    reranking.cached_scores("model", 1024, [("q", "alpha")], compute)
    reranking.cached_scores("model", 1024, [("q", "alpha"), ("q", "beta")], compute)

    assert computed == [("q", "alpha"), ("q", "beta")]


def test_scores_keep_their_order_when_partially_cached() -> None:
    _clear()
    reranking.cached_scores("model", 1024, [("q", "b")], lambda pairs: [2.0])

    scores = reranking.cached_scores(
        "model", 1024, [("q", "a"), ("q", "b"), ("q", "c")],
        lambda pairs: [1.0 if evidence == "a" else 3.0 for _q, evidence in pairs],
    )

    assert scores == [1.0, 2.0, 3.0]


def test_a_different_length_or_model_is_a_different_entry() -> None:
    _clear()
    reranking.cached_scores("model", 1024, [("q", "a")], lambda pairs: [1.0])
    assert reranking.cached_scores("model", 512, [("q", "a")], lambda pairs: [9.0]) == [9.0]
    assert reranking.cached_scores("other", 1024, [("q", "a")], lambda pairs: [7.0]) == [7.0]


def test_the_cache_is_bounded() -> None:
    _clear()
    limit = reranking._SCORE_CACHE_ENTRIES
    reranking.cached_scores(
        "model", 1024,
        [("q", str(index)) for index in range(limit + 50)],
        lambda pairs: [0.0] * len(pairs),
    )
    assert len(reranking._SCORE_CACHE) <= limit
