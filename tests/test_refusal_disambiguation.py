"""The two refusals a user can hit must not read the same.

"Nothing was retrieved" is an indexing problem. "Material was retrieved but the
claims written from it could not be verified" is a phrasing or threshold problem.
They used to produce an identical message with no sources, which made a
verification failure look like an empty index.
"""

import asyncio

from langchain_core.documents import Document

import app.workflow as workflow_module
from app.config import Settings
from app.llm import GroundedAnswer, GroundingVerdict, TokenUsage
from app.models import RagRequest


class _Retriever:
    def __init__(self, documents: list[Document]) -> None:
        self._documents = documents

    async def ainvoke_scoped(self, *args, **kwargs) -> list[Document]:
        return list(self._documents)

    async def ainvoke(self, *args, **kwargs) -> list[Document]:
        return list(self._documents)

    def drain_usage(self) -> dict[str, int]:
        return {"embedding_tokens": 0, "read_units": 0, "retry_count": 0}


class _Planner:
    def __init__(self, *args, **kwargs) -> None:
        self.last_usage = TokenUsage()
        self.model_name = "fake-planner"

    async def plan(self, question, *args, **kwargs):
        from app.llm import QueryPlan

        return QueryPlan(queries=[question], rerank_query=question)


class _Reranker:
    async def rerank(self, query, documents, **kwargs):
        for document in documents:
            document.metadata["rerank_score"] = 0.8
        return list(documents)


class _Generator:
    def __init__(self, *args, **kwargs) -> None:
        self.last_usage = TokenUsage()
        self.model_name = "fake-generator"

    async def answer(self, *args, **kwargs) -> GroundedAnswer:
        return GroundedAnswer(
            answer="The shift summary carries a ticket count [SOURCE 1].",
            citations=[1],
            missing_information=[],
        )

    async def repair(self, *args, **kwargs) -> GroundedAnswer:
        return GroundedAnswer(
            answer="The shift summary carries a ticket count [SOURCE 1].",
            citations=[1],
            missing_information=[],
        )


class _RejectingVerifier:
    def __init__(self, *args, **kwargs) -> None:
        self.last_usage = TokenUsage()
        self.model_name = "fake-grounding"
        self.last_rejections = []

    async def verify(self, *args, **kwargs) -> GroundingVerdict:
        return GroundingVerdict(
            supported=False,
            unsupported_claims=["The shift summary carries a ticket count [SOURCE 1]."],
            reason_code="UNSUPPORTED_CLAIM",
        )

    async def attach_missing_citations(self, documents, answer) -> GroundedAnswer:
        return answer


class _RecordingSafeResponder:
    reasons: list[str] = []

    def __init__(self, *args, **kwargs) -> None:
        self.last_usage = TokenUsage()
        self.model_name = "fake-safe-responder"

    async def generate(self, question, language, reason) -> str:
        _RecordingSafeResponder.reasons.append(reason)
        return f"refusal:{reason}"


def _document() -> Document:
    return Document(
        page_content="| Member | Wire name |\n|---|---|\n| ticketsCount | `tickets_count` |",
        metadata={
            "chunk_id": "c1",
            "source_id": "s1",
            "score": 0.9,
            "source_type": "PAGE",
            "title": "Event contract",
            "reference": "EVT-1",
            "source_url": "https://example.atlassian.net/wiki/EVT-1",
            "language": "en",
            "locator": "page:1",
        },
    )


def _run(monkeypatch, documents: list[Document]):
    _RecordingSafeResponder.reasons = []
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: _Retriever(documents)),
    )
    monkeypatch.setattr(workflow_module, "BilingualQueryPlanner", _Planner)
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: _Reranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", _Generator)
    monkeypatch.setattr(
        workflow_module, "LangChainSafeResponseGenerator", _RecordingSafeResponder
    )
    monkeypatch.setattr(
        workflow_module, "LocalCitationGroundingVerifier", _RejectingVerifier
    )
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="What does POS_CLOSE_SHIFT require?",
        accessPolicyIds=["project:DEMO"],
    )
    return asyncio.run(
        workflow_module.AuthorizedRagWorkflow(
            Settings(_env_file=None, environment="development"), request
        ).run()
    )


def test_ungroundable_evidence_says_unverified_and_names_what_was_read(monkeypatch) -> None:
    response = _run(monkeypatch, [_document()])
    assert _RecordingSafeResponder.reasons[-1] == "UNVERIFIED_EVIDENCE"
    assert response.evidence_status == "UNVERIFIED"
    assert response.confidence == "NONE"
    # The pages that were read are the actionable part of this refusal.
    assert [source.title for source in response.sources] == ["Event contract"]
    assert response.sources[0].url == "https://example.atlassian.net/wiki/EVT-1"


def test_empty_retrieval_still_says_insufficient_and_names_nothing(monkeypatch) -> None:
    response = _run(monkeypatch, [])
    assert _RecordingSafeResponder.reasons[-1] == "INSUFFICIENT_EVIDENCE"
    assert response.evidence_status == "INSUFFICIENT"
    assert response.sources == []


def test_the_two_refusals_are_distinguishable_to_the_client(monkeypatch) -> None:
    unverified = _run(monkeypatch, [_document()])
    empty = _run(monkeypatch, [])
    assert unverified.evidence_status != empty.evidence_status
    assert unverified.answer != empty.answer
