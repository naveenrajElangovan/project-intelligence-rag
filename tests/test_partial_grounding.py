"""One unsupported sentence must not discard the sentences that verified.

Observed on a live request: 5 cited claims, 1 rejected at score 0.065 against a
0.35 threshold. The four verified claims were thrown away and the user got a
refusal for a question the corpus answers. Claim-level pruning already existed
but ran only for PROJECT_OVERVIEW and ENTITY_OVERVIEW; every other intent went
straight to regeneration and then to a refusal.
"""

import asyncio

from langchain_core.documents import Document

import app.workflow as workflow_module
from app.config import Settings
from app.llm import GroundedAnswer, GroundingVerdict, TokenUsage
from app.models import RagRequest
from app.workflow_nodes.answering import _note_removed_claims

GOOD = "`POS_LOGIN` is event id 101 at version 0.3 [SOURCE 1]."
BAD = "The login event carries a terminal serial number field [SOURCE 1]."


class _Retriever:
    def __init__(self, documents): self._documents = documents
    async def ainvoke_scoped(self, *a, **k): return list(self._documents)
    async def ainvoke(self, *a, **k): return list(self._documents)
    def drain_usage(self): return {"embedding_tokens": 0, "read_units": 0, "retry_count": 0}


class _Planner:
    def __init__(self, *a, **k):
        self.last_usage = TokenUsage(); self.model_name = "fake-planner"
    async def plan(self, question, *a, **k):
        from app.llm import QueryPlan
        return QueryPlan(queries=[question], rerank_query=question)


class _Reranker:
    async def rerank(self, query, documents, **k):
        for document in documents:
            document.metadata["rerank_score"] = 0.8
        return list(documents)


class _Generator:
    repairs = 0
    def __init__(self, *a, **k):
        self.last_usage = TokenUsage(); self.model_name = "fake-generator"
    async def answer(self, *a, **k):
        return GroundedAnswer(answer=f"{GOOD} {BAD}", citations=[1], missing_information=[])
    async def repair(self, *a, **k):
        _Generator.repairs += 1
        return GroundedAnswer(answer=f"{GOOD} {BAD}", citations=[1], missing_information=[])


class _PartialVerifier:
    """Rejects only BAD, on every call -- as the real verifier would."""

    def __init__(self, *a, **k):
        self.last_usage = TokenUsage()
        self.model_name = "fake-grounding"
        self.last_rejections = []
        self.calls = 0

    async def verify(self, question, documents, answer, **k):
        self.calls += 1
        if BAD.split(" [SOURCE")[0] in answer.answer:
            return GroundingVerdict(
                supported=False, unsupported_claims=[BAD], reason_code="UNSUPPORTED_CLAIM"
            )
        return GroundingVerdict(supported=True, unsupported_claims=[], reason_code="SUPPORTED")

    async def attach_missing_citations(self, documents, answer):
        return answer


class _Safe:
    reasons = []
    def __init__(self, *a, **k):
        self.last_usage = TokenUsage(); self.model_name = "fake-safe"
    async def generate(self, question, language, reason):
        _Safe.reasons.append(reason)
        return f"refusal:{reason}"


def _document(text: str) -> Document:
    return Document(
        page_content=text,
        metadata={
            "chunk_id": "c1", "source_id": "s1", "score": 0.9, "source_type": "PAGE",
            "title": "Event contract", "reference": "EVT-025",
            "source_url": "https://example.atlassian.net/wiki/EVT-025",
            "language": "en", "locator": "page:1",
        },
    )


def _run(monkeypatch, question: str):
    _Safe.reasons = []
    _Generator.repairs = 0
    documents = [_document("| `LOGIN_POS_EVENT` | `POS_LOGIN` | 101 | 0.3 | publishes |")]
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever, "create",
        classmethod(lambda cls, **k: _Retriever(documents)),
    )
    monkeypatch.setattr(workflow_module, "BilingualQueryPlanner", _Planner)
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: _Reranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", _Generator)
    monkeypatch.setattr(workflow_module, "LangChainSafeResponseGenerator", _Safe)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", _PartialVerifier)
    request = RagRequest(
        projectId="DEMO", collectionName="project-intelligence",
        question=question, accessPolicyIds=["project:DEMO"],
    )
    return asyncio.run(
        workflow_module.AuthorizedRagWorkflow(
            Settings(_env_file=None, environment="development"), request
        ).run()
    )


def test_verified_claim_survives_an_unsupported_sibling():
    # A plain factual question routes CODE_ASSISTED, which previously refused here.
    import pytest
    monkeypatch = pytest.MonkeyPatch()
    try:
        response = _run(monkeypatch, "Give me the POS login event details")
    finally:
        monkeypatch.undo()
    assert "101" in response.answer
    assert "terminal serial number" not in response.answer
    assert response.evidence_status == "SUFFICIENT"
    assert _Safe.reasons == []


def test_the_removal_is_declared_not_hidden():
    import pytest
    monkeypatch = pytest.MonkeyPatch()
    try:
        response = _run(monkeypatch, "Give me the POS login event details")
    finally:
        monkeypatch.undo()
    assert any("could not be verified" in item for item in response.missing_information)


def test_pruning_is_tried_before_the_expensive_regeneration():
    import pytest
    monkeypatch = pytest.MonkeyPatch()
    try:
        _run(monkeypatch, "Give me the POS login event details")
    finally:
        monkeypatch.undo()
    assert _Generator.repairs == 0


def test_sources_are_reported_for_the_surviving_claim():
    import pytest
    monkeypatch = pytest.MonkeyPatch()
    try:
        response = _run(monkeypatch, "Give me the POS login event details")
    finally:
        monkeypatch.undo()
    assert [source.reference for source in response.sources] == ["EVT-025"]


def test_note_helper_is_idempotent_and_pluralises():
    answer = GroundedAnswer(answer="a [SOURCE 1].", citations=[1], missing_information=[])
    once = _note_removed_claims(answer, 1)
    assert once.missing_information == [
        "One statement drafted from the sources could not be verified against them "
        "and was removed."
    ]
    assert _note_removed_claims(once, 1).missing_information == once.missing_information
    many = _note_removed_claims(answer, 3)
    assert many.missing_information[0].startswith("3 statements")


def test_note_helper_is_a_no_op_when_nothing_was_removed():
    answer = GroundedAnswer(answer="a [SOURCE 1].", citations=[1], missing_information=[])
    assert _note_removed_claims(answer, 0) is answer
