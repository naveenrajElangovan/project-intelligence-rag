from langchain_core.documents import Document

from app.workflow_nodes.retrieval import (
    _prefilter_candidates,
    _preserve_primary_query_candidates,
)


def _document(chunk_id: str, primary_rank: int = 0) -> Document:
    metadata: dict[str, object] = {"chunk_id": chunk_id}
    if primary_rank:
        metadata["primary_query_rank"] = primary_rank
    return Document(page_content=chunk_id, metadata=metadata)


def test_original_query_candidates_reach_the_reranker_without_forcing_all_of_them() -> None:
    generic = [_document("generic-1"), _document("generic-2"), _document("generic-3")]
    primary_second = _document("primary-2", 2)
    primary_first = _document("primary-1", 1)

    preserved = _preserve_primary_query_candidates(
        [*generic, primary_second, primary_first],
        limit=3,
        reserve=2,
    )

    assert [document.metadata["chunk_id"] for document in preserved] == [
        "primary-1",
        "primary-2",
        "generic-1",
    ]


def test_original_query_candidate_preservation_deduplicates_by_chunk_id() -> None:
    first = _document("same", 1)
    duplicate = _document("same")

    preserved = _preserve_primary_query_candidates(
        [duplicate, first],
        limit=3,
    )

    assert [document.metadata["chunk_id"] for document in preserved] == ["same"]


def test_primary_query_candidate_bypasses_only_the_low_overlap_prefilter() -> None:
    high = [_document(f"high-{index}") for index in range(7)]
    for document in high:
        document.metadata.update({"score": 0.9, "exact_term_ratio": 0.0})
    dropped = _document("low-generic")
    dropped.metadata.update({"score": 0.1, "exact_term_ratio": 0.0})
    primary = _document("low-primary", 1)
    primary.metadata.update({"score": 0.1, "exact_term_ratio": 0.0})

    kept, reasons = _prefilter_candidates([*high, dropped, primary])

    kept_ids = {document.metadata["chunk_id"] for document in kept}
    assert "low-primary" in kept_ids
    assert "low-generic" not in kept_ids
    assert reasons["zero_overlap_low_dense"] == 1


def _scored(chunk_id: str, score: float, overlap: float = 0.0) -> Document:
    return Document(
        page_content=chunk_id,
        metadata={"chunk_id": chunk_id, "score": score, "exact_term_ratio": overlap},
    )


def test_prefilter_keeps_a_uniformly_strong_pool_intact() -> None:
    """Removal must follow candidate weakness, never pool size.

    The prefilter previously dropped everything below the pool's own median dense
    score, so roughly half of any pool was discarded however strong it was. A
    documentation page whose rows share few literal terms with the question -- the
    paraphrased match dense retrieval exists to find -- was exactly what went.
    """

    pool = [_scored(f"strong-{index}", 0.80) for index in range(20)]

    kept, reasons = _prefilter_candidates(pool)

    assert len(kept) == len(pool)
    assert reasons["zero_overlap_low_dense"] == 0


def test_prefilter_never_removes_more_than_the_configured_fraction() -> None:
    """A mistuned floor must degrade recall slightly, not delete the pool."""

    pool = [_scored(f"weak-{index}", 0.01) for index in range(20)]

    kept, reasons = _prefilter_candidates(
        pool, minimum_dense_score=1.0, maximum_removed_fraction=0.34
    )

    assert reasons["zero_overlap_low_dense"] == int(20 * 0.34)
    assert len(kept) == 20 - int(20 * 0.34)


def test_prefilter_ceiling_keeps_the_strongest_borderline_candidates() -> None:
    """When the ceiling binds, the weakest go first."""

    pool = [_scored(f"c-{index}", 0.05 + index / 100) for index in range(10)]

    kept, _ = _prefilter_candidates(pool)

    survivors = sorted(round(document.metadata["score"], 2) for document in kept)
    assert survivors == [
        round(0.05 + index / 100, 2) for index in range(int(10 * 0.34), 10)
    ]
