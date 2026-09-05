"""Where an empty result is a failure rather than a refusal.

Two of these were real defects. A broad question ("what is this project about")
scores low against every passage, so an absolute rerank floor emptied a pool
that did contain the overview pages -- 43 candidates in, zero out. And the
rerank floor was language-blind, so a Spanish question reached the generator
with 4 documents where the identical English one got 12.

A third apparent defect was not one: total entity mismatch fails closed on
purpose, and test_entity_evidence_scope pins that. Answering about one
application from another application's evidence is worse than declining, so the
guard here is deliberately narrow -- opt-in, and only for routes whose question
is broad by construction.
"""

import asyncio

from langchain_core.documents import Document

from app.config import Settings
from app.reranking import LocalMultilingualReranker, _is_cross_language
from app.workflow_nodes.answering import _scope_documents_to_entity


class _Reranker(LocalMultilingualReranker):
    def __init__(self, scores, **overrides):
        settings = Settings(_env_file=None, environment="development")
        super().__init__(
            "model",
            device="cpu",
            model_path="",
            revision="",
            top_n=overrides.get("top_n", 8),
            score_threshold=overrides.get("threshold", 0.10),
            exact_code_score_threshold=0.65,
            exact_code_retrieval_score_floor=0.80,
            cross_language_score_threshold=overrides.get("cross", 0.05),
            max_chunks_per_source=3,
        )
        self._scores = scores
        self._settings = settings

    def _predict(self, query, documents):
        return self._scores[: len(documents)]


def _documents(count: int, language: str = "en") -> list[Document]:
    return [
        Document(
            page_content=f"passage {index}",
            metadata={"source_id": f"s{index}", "language": language, "score": 0.5},
        )
        for index in range(count)
    ]


def test_a_threshold_that_rejects_everything_keeps_the_best() -> None:
    """Observed: a generic question scored every candidate below the floor."""

    # Raw logits well below the 0.10 normalized floor.
    reranker = _Reranker([-6.0, -5.0, -4.0])
    ranked = asyncio.run(
        reranker.rerank(
            "what is this project about", _documents(3), allow_threshold_bypass=True
        )
    )

    assert ranked, "an empty result is a failed request, not a quality decision"
    assert reranker.last_threshold_bypassed is True
    assert ranked[0].page_content == "passage 2", "the best candidate must lead"


def test_a_normal_threshold_still_filters() -> None:
    reranker = _Reranker([5.0, -6.0])
    ranked = asyncio.run(
        reranker.rerank("a specific question", _documents(2), allow_threshold_bypass=True)
    )

    assert len(ranked) == 1
    assert reranker.last_threshold_bypassed is False


def test_an_empty_result_stays_empty_without_the_opt_in() -> None:
    """The default contract is unchanged: a refusal is a refusal."""

    reranker = _Reranker([-6.0, -5.0])
    assert asyncio.run(reranker.rerank("a specific question", _documents(2))) == []
    assert reranker.last_threshold_bypassed is False


def test_cross_language_evidence_gets_the_lower_bar() -> None:
    """-2.0 normalizes to ~0.119: over the 0.05 cross-language bar, under 0.10."""

    reranker = _Reranker([-2.0], threshold=0.20, cross=0.05)
    ranked = asyncio.run(
        reranker.rerank("¿qué contiene?", _documents(1, "en"), query_language="es")
    )

    assert ranked, "cross-language evidence must not be held to the same floor"
    assert reranker.last_cross_language_documents == 1
    assert reranker.last_threshold_bypassed is False


def test_same_language_evidence_keeps_the_normal_bar() -> None:
    reranker = _Reranker([-2.0, 5.0], threshold=0.20, cross=0.05)
    ranked = asyncio.run(
        reranker.rerank("a question", _documents(2, "en"), query_language="en")
    )

    assert len(ranked) == 1
    assert reranker.last_cross_language_documents == 0


def test_cross_language_needs_both_sides_named() -> None:
    document = _documents(1, "und")[0]
    assert _is_cross_language("es", document) is False
    assert _is_cross_language("", _documents(1, "en")[0]) is False
    assert _is_cross_language("es", _documents(1, "en")[0]) is True


def test_entity_scoping_still_fails_closed_on_a_total_mismatch() -> None:
    """Deliberate, and it must stay that way.

    Answering about one application from another application's evidence is worse
    than declining, so this is not covered by the bypass above.
    """

    documents = [
        Document(page_content="a", metadata={"title": "A", "entity_key": "bot"}),
        Document(page_content="b", metadata={"title": "B", "entity_key": "bot"}),
    ]
    scoped, excluded, _titles, bypassed = _scope_documents_to_entity(documents, "pos")

    assert scoped == []
    assert excluded == 2 and bypassed is False


def test_entity_scoping_still_narrows_when_something_survives() -> None:
    documents = [
        Document(page_content="a", metadata={"title": "A", "entity_key": "bot"}),
        Document(page_content="b", metadata={"title": "B", "entity_key": "pos"}),
    ]
    scoped, excluded, _titles, bypassed = _scope_documents_to_entity(documents, "pos")

    assert [d.page_content for d in scoped] == ["b"]
    assert excluded == 1 and bypassed is False
