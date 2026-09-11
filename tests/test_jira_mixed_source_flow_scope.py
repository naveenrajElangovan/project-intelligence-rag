import asyncio
from app.config import Settings
from app.models import RagRequest
from app.vocabulary import CorpusVocabulary
from app.workflow_nodes.planning import PlanningNodesMixin


class Workflow(PlanningNodesMixin):
    def __init__(self, question):
        self._request = RagRequest(
            projectId="DEMO",
            collectionName="knowledge",
            question=question,
            accessPolicyIds=["project:DEMO"],
        )
        self._settings = Settings()
        self._vocabulary = CorpusVocabulary(
            entities=("pos", "bot"), source_types=("CODE", "PAGE", "ISSUE", "ATTACHMENT")
        )

    async def _resolve_conversation_question(self, question, language):
        return question


def test_implementation_flow_preserves_code_documentation_route_with_jira_present():
    result = asyncio.run(
        Workflow("How does the POS settlement workflow operate?")._plan_queries_core({})
    )
    assert result["query_intent"] == "CODE_ASSISTED"
    assert set(result["source_types"]) == {"CODE", "PAGE"}
    assert result["source_route"] == "CONFLUENCE_GITHUB"
