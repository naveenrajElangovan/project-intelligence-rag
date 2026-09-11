import asyncio
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from app.workflow_nodes.retrieval import RetrievalNodesMixin


class Harness(RetrievalNodesMixin):
    def __init__(self, question, documents):
        self._request = SimpleNamespace(question=question, project_id="DEMO")
        self.calls = []

        async def sections(value):
            self.calls.append(value)
            return documents

        self._retriever = SimpleNamespace(ainvoke_jira_sections=sections)


@pytest.mark.parametrize(
    "question",
    [
        "What is the current status of OPS-72?",
        "¿Cuál es la descripción de SERVICE_2-106?",
        "What changed in historical event 99 for HELP-8?",
    ],
)
def test_exact_sections_do_not_need_dense_retrieval_or_translation(question):
    document = Document(
        page_content="Authorized evidence",
        metadata={
            "source_id": "jira:cloud:72",
            "locator": "current",
            "project_id": "DEMO",
        },
    )
    workflow = Harness(question, [document])

    async def run():
        state = await workflow._retrieve({"queries": (question,), "query_intent": "DELIVERY"})
        result = await workflow._feature_affinity(state)
        assert result["candidates"] == [document]
        assert state["dense_candidate_count"] == 0
        assert state["translation_slot"] is None
        assert workflow.calls == [question]

    asyncio.run(run())


@pytest.mark.parametrize(
    "question, intent, documents, expected_calls",
    [
        ("What comment is on OPS-72?", "DELIVERY", [], 1),
        ("Where is OPS-72 implemented?", "CODE_ASSISTED", [Document(page_content="x")], 0),
        ("Tell me about OPS-72", "DELIVERY", [Document(page_content="x")], 0),
    ],
)
def test_missing_or_ambiguous_section_continues_normal_path(
    question, intent, documents, expected_calls
):
    workflow = Harness(question, documents)
    # The normal path reaches its planner; this minimal harness intentionally
    # has no planner so an accidental early return fails this assertion.
    with pytest.raises(AttributeError, match="_query_planner_factory"):
        asyncio.run(
            workflow._retrieve(
                {
                    "queries": (question,),
                    "query_intent": intent,
                    "translation_slot": 0,
                }
            )
        )
    assert len(workflow.calls) == expected_calls


def test_absent_exact_current_issue_does_not_search_unrelated_tickets():
    question = "What is the current status of MISSING-999?"
    workflow = Harness(question, [])
    result = asyncio.run(workflow._retrieve({"queries": (question,), "query_intent": "DELIVERY"}))
    assert result["candidates"] == []
    assert result["dense_candidate_count"] == 0


def test_multiple_current_keys_use_separate_authorized_exact_reads():
    question = "Compare current statuses of OPS-72 and HELP-73"
    workflow = Harness(question, [])

    async def sections(value):
        workflow.calls.append(value)
        key = "OPS-72" if "OPS-72" in value else "HELP-73"
        return [
            Document(
                page_content="Current",
                metadata={
                    "provider": "JIRA",
                    "jira_chunk_kind": "CURRENT",
                    "issue_key": key,
                    "source_id": "jira:cloud:" + key,
                },
            )
        ]

    workflow._retriever.ainvoke_jira_sections = sections
    result = asyncio.run(workflow._retrieve({"queries": (question,), "query_intent": "DELIVERY"}))
    assert workflow.calls == [
        "What is the current status of OPS-72?",
        "What is the current status of HELP-73?",
    ]
    assert [d.metadata["issue_key"] for d in result["candidates"]] == ["OPS-72", "HELP-73"]
    assert result["dense_candidate_count"] == 0
