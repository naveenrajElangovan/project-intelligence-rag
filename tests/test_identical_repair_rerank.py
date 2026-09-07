"""Completeness repair reuses scoring only for byte-identical scorer inputs."""

import asyncio

import pytest
from langchain_core.documents import Document

from app.config import Settings
from app.models import RagRequest
from app.vocabulary import CorpusVocabulary
from app.workflow_nodes.answering import AnswerNodesMixin
from app.workflow_nodes.retrieval import RetrievalNodesMixin
from app.workflow_support.completeness import _completeness_repair_query


def _document(chunk_id: str) -> Document:
    return Document(
        page_content=f"Evidence for {chunk_id}.",
        metadata={
            "chunk_id": chunk_id,
            "project_id": "DEMO",
            "access_policy_ids": ["project:DEMO"],
            "source_type": "PAGE",
            "score": 0.8,
            "reference": chunk_id,
        },
    )


class RecordingRetriever:
    def __init__(self, results: list[list[Document]]) -> None:
        self.results = results
        self.queries: list[str] = []

    async def retrieve(self, query: str) -> list[Document]:
        self.queries.append(query)
        return self.results[len(self.queries) - 1]


class RecordingScorer:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[str, ...]]] = []

    async def rerank(self, query: str, documents: list[Document], **_kwargs):
        ids = tuple(str(document.metadata["chunk_id"]) for document in documents)
        self.calls.append((query, ids))
        for index, document in enumerate(documents):
            document.metadata["rerank_score"] = 0.9 - index / 10
        return list(documents)


class RerankHarness(RetrievalNodesMixin, AnswerNodesMixin):
    def __init__(self, scorer: RecordingScorer) -> None:
        self._settings = Settings(_env_file=None, environment="development")
        self._request = RagRequest(
            projectId="DEMO",
            collectionName=self._settings.chroma_collection,
            question="same query",
            accessPolicyIds=["project:DEMO"],
        )
        self._vocabulary = CorpusVocabulary()
        self._reranker = scorer


async def _run_two_passes(second_query: str, second_ids: tuple[str, ...]):
    scorer = RecordingScorer()
    workflow = RerankHarness(scorer)
    retriever = RecordingRetriever(
        [[_document("a"), _document("b")], [_document(value) for value in second_ids]]
    )
    first_candidates = await retriever.retrieve("same query")
    first = await workflow._rerank(
        {"candidates": first_candidates, "rerank_query": "same query"}
    )
    second_candidates = await retriever.retrieve(second_query)
    second = await workflow._rerank(
        {
            "candidates": second_candidates,
            "rerank_query": second_query,
            "prior_documents": first["documents"],
            "scored_query": first["scored_query"],
            "scored_candidate_ids": first["scored_candidate_ids"],
        }
    )
    return retriever, scorer, second


def test_identical_repair_query_and_candidate_ids_skip_second_scoring_pass() -> None:
    retriever, scorer, second = asyncio.run(
        _run_two_passes("same query", ("b", "a"))
    )

    assert retriever.queries == ["same query", "same query"]
    assert len(scorer.calls) == 1
    assert second["rerank_skipped"] is True


def test_repair_query_is_the_query_used_by_the_second_scorer() -> None:
    workflow = RerankHarness(RecordingScorer())
    documents = [_document("a")]
    expected = _completeness_repair_query(
        "Which fields are required?", documents, ("field:amount",)
    )
    repaired = asyncio.run(
        workflow._repair_completeness(
            {
                "resolved_question": "Which fields are required?",
                "documents": documents,
                "missing_requirements": ("field:amount",),
            }
        )
    )

    assert repaired["queries"] == (expected,)
    assert repaired["rerank_query"] == expected
    assert repaired["rerank_queries"] == (expected,)


@pytest.mark.parametrize(
    ("second_query", "second_ids"),
    (("different query", ("a", "b")), ("same query", ("a", "c"))),
)
def test_changed_repair_query_or_candidate_ids_execute_scoring(
    second_query: str, second_ids: tuple[str, ...]
) -> None:
    _retriever, scorer, second = asyncio.run(
        _run_two_passes(second_query, second_ids)
    )

    assert len(scorer.calls) == 2
    assert second["rerank_skipped"] is False
