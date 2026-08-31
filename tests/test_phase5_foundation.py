import asyncio

import pytest
from fastapi import HTTPException
from langchain_core.documents import Document

from app.config import Settings
from app.main import _acquire_request_slot
from app.models import RagResponse
from app.reranking import progressive_rerank_candidates
from app.workflow_nodes.retrieval import (
    RetrievalNodesMixin,
    _source_volume_discounted_score,
)


def _document(
    chunk_id: str,
    score: float,
    source_type: str = "CODE",
    *,
    anchor: bool = False,
) -> Document:
    return Document(
        page_content=chunk_id,
        metadata={
            "chunk_id": chunk_id,
            "score": score,
            "retrieval_fused_score": score,
            "source_type": source_type,
            "identifier_anchor": anchor,
        },
    )


def test_progressive_rerank_keeps_anchor_and_source_diversity() -> None:
    documents = [_document(f"code-{index}", 1.0 - index / 100) for index in range(20)]
    documents.extend(
        [
            _document("page", 0.01, "PAGE"),
            _document("issue", 0.02, "ISSUE"),
            _document("anchor", 0.0, anchor=True),
        ]
    )

    narrowed = progressive_rerank_candidates(documents, 8)

    assert len(narrowed) == 8
    assert "anchor" in {document.metadata["chunk_id"] for document in narrowed}
    assert {document.metadata["source_type"] for document in narrowed} >= {
        "CODE",
        "PAGE",
        "ISSUE",
    }


def test_progressive_rerank_keeps_original_query_candidates() -> None:
    documents = [_document(f"generic-{index}", 1.0 - index / 100) for index in range(20)]
    primary = _document("primary", 0.0, "PAGE")
    primary.metadata["primary_query_rank"] = 1
    documents.append(primary)

    narrowed = progressive_rerank_candidates(documents, 8)

    assert "primary" in {document.metadata["chunk_id"] for document in narrowed}


def test_source_volume_discount_is_neutral_for_one_and_never_excludes() -> None:
    score = 0.75

    assert _source_volume_discounted_score(
        score, source_candidate_count=1, strength=0.4
    ) == score
    discounted = _source_volume_discounted_score(
        score, source_candidate_count=20, strength=0.4
    )
    assert 0 < discounted < score


def test_source_volume_discount_strength_is_validated() -> None:
    Settings(_env_file=None, environment="development", source_volume_discount_strength=1)
    with pytest.raises(ValueError, match="SOURCE_VOLUME_DISCOUNT_STRENGTH"):
        Settings(
            _env_file=None,
            environment="development",
            source_volume_discount_strength=1.01,
        )


def test_load_shedding_rejects_before_waiting_for_work() -> None:
    async def scenario() -> None:
        settings = Settings(max_inflight_requests=1, load_shed_wait_seconds=0.001)
        slot = await _acquire_request_slot(settings)
        try:
            with pytest.raises(HTTPException) as failure:
                await _acquire_request_slot(settings)
            assert failure.value.status_code == 503
            assert failure.value.headers == {"Retry-After": "1"}
        finally:
            slot.release()
            await asyncio.sleep(0)

    asyncio.run(scenario())


def test_degradation_is_explicit_and_defaults_to_empty() -> None:
    response = RagResponse(
        answer="Verified answer",
        confidence="HIGH",
        projectId="project-1",
        sources=[],
        missingInformation=[],
    )

    assert response.degradation == []
    assert response.model_dump(by_alias=True)["degradation"] == []


def _code_assisted_workflow():
    class Reranker:
        async def rerank(self, _query, documents, *, top_n=None, **_kwargs):
            return list(documents)[:top_n]

    class Workflow(RetrievalNodesMixin):
        pass

    workflow = Workflow()
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._reranker = Reranker()
    workflow._vocabulary = type("Vocabulary", (), {"code_extensions": (".py",)})()
    return workflow


def test_code_assisted_ranks_both_source_families_without_reserved_slots() -> None:
    """Neither family holds reserved slots: the ranked order decides the window.

    The previous contract reranked PAGE and CODE separately and merged them as
    ``[*pages, *code]`` under per-family caps of six and two, so code could never
    exceed two documents however well it scored. The application source is
    authoritative for declarations, so both families now compete in one pass.
    """

    workflow = _code_assisted_workflow()
    window = workflow._settings.mixed_source_top_n
    limit = workflow._settings.max_chunks_per_source

    code_first = [
        _document(f"code-{index}", 1 - index / 100, "CODE") for index in range(10)
    ] + [_document(f"page-{index}", 0.5 - index / 100, "PAGE") for index in range(10)]
    selected = asyncio.run(
        workflow._rerank_code_assisted("events", code_first, limit)
    )
    assert len(selected) == window
    # The old contract capped this at two regardless of score.
    assert sum(item.metadata["source_type"] == "CODE" for item in selected) == window

    page_first = [
        _document(f"page-{index}", 1 - index / 100, "PAGE") for index in range(10)
    ] + [_document(f"code-{index}", 0.5 - index / 100, "CODE") for index in range(10)]
    selected = asyncio.run(
        workflow._rerank_code_assisted("events", page_first, limit)
    )
    assert len(selected) == window
    assert sum(item.metadata["source_type"] == "PAGE" for item in selected) == window


def test_code_assisted_passes_the_source_limit_to_the_reranker() -> None:
    """One file must not be able to supply the whole window."""

    seen: dict[str, object] = {}

    class Reranker:
        async def rerank(self, _query, documents, *, top_n=None, **kwargs):
            seen.update(kwargs)
            return list(documents)[:top_n]

    class Workflow(RetrievalNodesMixin):
        pass

    workflow = Workflow()
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._reranker = Reranker()
    workflow._vocabulary = type("Vocabulary", (), {"code_extensions": (".py",)})()

    asyncio.run(
        workflow._rerank_code_assisted(
            "events", [_document("code-0", 0.9, "CODE")], 3
        )
    )

    assert seen.get("max_chunks_per_source") == 3


def test_source_type_scope_cannot_empty_non_empty_candidates() -> None:
    class Reranker:
        async def rerank(self, _query, documents, **_kwargs):
            return list(documents)

    class Workflow(RetrievalNodesMixin):
        pass

    workflow = Workflow()
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._reranker = Reranker()
    workflow._vocabulary = type("Vocabulary", (), {"code_extensions": ()})()
    candidates = [_document("issue", 0.8, "ISSUE")]

    selected = asyncio.run(
        workflow._rerank_code_assisted(
            "status", candidates, workflow._settings.max_chunks_per_source
        )
    )

    assert selected == candidates
    assert workflow._last_source_type_scope_bypassed is True
