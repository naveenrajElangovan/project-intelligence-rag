import asyncio

import pytest
from fastapi.testclient import TestClient
from langchain_core.documents import Document

from app.config import Settings
from app.llm import GroundedAnswer, generation_temperature
from app.main import app
from app.retrieval import ChromaAccessRetriever
from app.retry import is_transient_error, with_transient_retry
from app.workflow import _citations_valid, _expand_candidate_neighbors, _normalize_citations


class TransientFailure(RuntimeError):
    status_code = 503


def test_transient_retry_is_bounded() -> None:
    calls = 0

    async def operation() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise TransientFailure("temporarily unavailable")
        return "ok"

    value, retries = asyncio.run(
        with_transient_retry(
            operation, attempts=3, timeout_seconds=1, base_delay_seconds=0
        )
    )
    assert value == "ok"
    assert retries == 2
    assert calls == 3


def test_non_transient_failure_is_not_retried() -> None:
    calls = 0

    async def operation() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("invalid request")

    with pytest.raises(ValueError):
        asyncio.run(
            with_transient_retry(operation, attempts=3, timeout_seconds=1)
        )
    assert calls == 1


def test_monthly_embedding_quota_is_not_retried() -> None:
    error = RuntimeError(
        "429 RESOURCE_EXHAUSTED embedding token limit for the current month"
    )
    error.status_code = 429  # type: ignore[attr-defined]

    assert is_transient_error(error) is False


class SchemaIndex:
    def query(self, **kwargs):
        return {
            "ids": [["wrong-schema", "valid"]],
            "distances": [[0.1, 0.2]],
            "documents": [["stale evidence", "current evidence"]],
            "metadatas": [[
                        {
                            "chunk_text": "stale evidence",
                            "project_id": "DEMO",
                            "access_policy_id": "project:DEMO",
                            "schema_version": "2",
                            "embedding_model": "multilingual-e5-large",
                        }, {
                            "project_id": "DEMO",
                            "access_policy_id": "project:DEMO",
                            "schema_version": "3",
                            "embedding_model": "multilingual-e5-large",
                            "source_type": "ISSUE",
                            "issue_key": "T0-1",
                            "status": "To Do",
                            "priority": "Medium",
                        },
            ]],
        }


class FakeEmbedder:
    def embed_query(self, query):
        return [0.1, 0.2]


def test_retrieval_rejects_incompatible_records_and_reports_usage() -> None:
    retriever = ChromaAccessRetriever(
        index=SchemaIndex(),
        collection_name="project-intelligence",
        embedder=FakeEmbedder(),
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
        required_schema_version="3",
        required_embedding_model="multilingual-e5-large",
    )
    documents = asyncio.run(retriever.ainvoke("status"))
    assert [document.page_content for document in documents] == ["current evidence"]
    assert documents[0].metadata["issue_key"] == "T0-1"
    assert documents[0].metadata["status"] == "To Do"
    assert documents[0].metadata["priority"] == "Medium"
    assert retriever.drain_usage() == {
        "embedding_tokens": 0,
        "read_units": 0,
        "retry_count": 0,
    }


def test_every_material_sentence_requires_a_real_citation() -> None:
    assert _citations_valid(
        GroundedAnswer(answer="Supported claim [SOURCE 1].", citations=[1]), 1
    )


def test_explicit_source_markers_populate_structured_citations() -> None:
    value = _normalize_citations(
        GroundedAnswer(
            answer="First supported claim [SOURCE 2]. Second supported claim [SOURCE 1].",
            citations=[],
        )
    )
    assert value.citations == [2, 1]
    assert _citations_valid(value, 2)


def test_detached_explicit_marker_is_moved_before_sentence_punctuation() -> None:
    value = _normalize_citations(
        GroundedAnswer(answer="A supported material claim. [SOURCE 1]", citations=[])
    )
    assert value.answer == "A supported material claim [SOURCE 1]."
    assert value.citations == [1]
    assert _citations_valid(value, 1)


def test_combined_source_marker_is_canonicalized() -> None:
    value = _normalize_citations(
        GroundedAnswer(
            answer="A supported material claim [SOURCE 1, SOURCE 2].",
            citations=[],
        )
    )
    assert value.answer == "A supported material claim [SOURCE 1] [SOURCE 2]."
    assert value.citations == [1, 2]
    assert _citations_valid(value, 2)
    assert not _citations_valid(
        GroundedAnswer(
            answer="Supported claim [SOURCE 1]. Another unsupported factual claim.",
            citations=[1],
        ),
        1,
    )


def test_neighbor_expansion_is_bounded_by_source_limit() -> None:
    anchor = _document("a", 2, 0.9)
    before = _document("b", 1, 0.4)
    after = _document("c", 3, 0.3)
    result = _expand_candidate_neighbors(
        [anchor], [anchor, before, after], top_n=3, max_per_anchor=1, max_per_source=2
    )
    assert [item.metadata["chunk_id"] for item in result] == ["a", "b"]
    assert result[1].metadata["context_neighbor"] is True


def test_local_inference_has_an_explicit_off_switch() -> None:
    settings = Settings(
        _env_file=None, environment="development", llm_provider="ollama",
        local_inference_enabled=False,
    )
    assert settings.llm_configured is False


def test_temperature_policy_is_bounded_by_answer_type() -> None:
    settings = Settings(
        _env_file=None, environment="development", factual_temperature=0.0,
        synthesis_temperature=0.1,
    )

    assert generation_temperature(settings, "implementation") == 0.0
    assert generation_temperature(settings, "concise") == 0.0
    assert generation_temperature(settings, "project_overview") == 0.1
    assert generation_temperature(settings, "cross_source") == 0.1


def test_temperature_policy_can_be_disabled() -> None:
    settings = Settings(
        _env_file=None, environment="development", adaptive_temperature_enabled=False,
        factual_temperature=0.0,
        synthesis_temperature=0.1,
    )

    assert generation_temperature(settings, "project_overview") == 0.0


def test_content_safe_prometheus_endpoint() -> None:
    response = TestClient(app).get("/metrics")
    assert response.status_code == 200
    assert "pi_rag_stage_total" in response.text
    assert "question" not in response.text.lower()


def _document(chunk_id: str, ordinal: int, score: float) -> Document:
    return Document(
        page_content=f"chunk {ordinal}",
        metadata={
            "chunk_id": chunk_id,
            "chunk_ordinal": ordinal,
            "source_id": "source",
            "parent_id": "source",
            "source_version": "1",
            "rerank_score": score,
        },
    )
