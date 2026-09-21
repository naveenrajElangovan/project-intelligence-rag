import asyncio
from types import SimpleNamespace
import pytest
from app.workflow_nodes.planning import PlanningNodesMixin


class Harness(PlanningNodesMixin):
    def __init__(self, question, intent):
        self._request = SimpleNamespace(question=question)
        self._vocabulary = SimpleNamespace(
            source_types=("ISSUE", "ATTACHMENT", "CODE"), entities=()
        )
        self.intent = intent

    async def _plan_queries_core(self, state):
        return {"query_intent": self.intent, "source_types": ("ISSUE",)}


@pytest.mark.parametrize(
    "question,intent,expected",
    [
        ("What is in the attachment on OPS-19?", "DELIVERY", {"ISSUE", "ATTACHMENT"}),
        ("¿Qué contiene el adjunto de HELP-1?", "DELIVERY", {"ISSUE", "ATTACHMENT"}),
        ("What is the current status of OPS-19?", "DELIVERY", {"ISSUE"}),
        ("How is attachment processing implemented?", "IMPLEMENTATION", {"ISSUE"}),
    ],
)
def test_resolved_attachment_scope_matches_retrieval_scope(question, intent, expected):
    result = asyncio.run(Harness(question, intent)._plan_queries({}))
    assert set(result["resolved_request"].allowed_source_categories) == expected
