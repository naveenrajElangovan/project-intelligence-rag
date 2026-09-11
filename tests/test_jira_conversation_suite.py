import json
from pathlib import Path

import pytest

from app.models import ConversationContext, RagRequest, StructuredConversationScope
from app.providers.contracts import ExecutionMode, ProviderName
from app.providers.router import select_providers
from app.workflow_support.fail_closed import clarification_response


CASES = json.loads(
    (Path(__file__).parents[1] / "evaluation" / "jira_conversation_suite.json").read_text()
)
ENABLED = (ProviderName.JIRA, ProviderName.GITHUB, ProviderName.CONFLUENCE)


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["question"])
def test_bilingual_structured_jira_conversation_cases(case):
    scope = StructuredConversationScope(
        provider="JIRA",
        resourceType="ISSUE",
        filters={"labels": ("POS",)},
        operation="COUNT",
        complete=True,
        pageSize=50,
        nextOffset=50,
        activeSubject="Jira tickets matching POS",
    )

    selection = select_providers(case["question"], ENABLED, scope)

    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.reason == "JIRA_STRUCTURED_CONTEXT_INHERITED"
    query = selection.structured_query
    assert query is not None
    assert query.operation.value == case["operation"]
    assert query.offset == case.get("offset", 0)
    assert query.group_by == case.get("groupBy")
    assert {key: list(values) for key, values in query.filters.items()} == case["filters"]


def test_structured_show_more_reaches_provider_router_before_legacy_clarification() -> None:
    request = RagRequest(
        projectId="T2.0",
        collectionName="project-intelligence",
        question="Show more.",
        accessPolicyIds=["project:T2.0"],
        conversationContext=ConversationContext(
            structuredScope=StructuredConversationScope(
                provider="JIRA",
                filters={"labels": ("POS",)},
                operation="LIST",
                complete=True,
                pageSize=50,
                nextOffset=50,
                activeSubject="Jira tickets matching POS",
            )
        ),
    )

    assert clarification_response(request, (), ("ISSUE",)) is None
    selection = select_providers(
        request.question, ENABLED, request.conversation_context.structured_scope
    )
    assert selection.mode == ExecutionMode.STRUCTURED
    assert selection.structured_query is not None
    assert selection.structured_query.offset == 50
