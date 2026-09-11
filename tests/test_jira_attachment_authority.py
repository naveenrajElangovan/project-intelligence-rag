import pytest
from langchain_core.documents import Document

from app.llm import GroundedAnswer
from app.workflow_support.query_analysis import _source_authority_valid


@pytest.mark.parametrize(
    "provider,source,parent,accepted",
    [
        ("JIRA", "jira:cloud:attachment:123", "jira:cloud:issue:456", True),
        ("JIRA", "jira:cloud:attachment:123", "jira:other:issue:456", False),
        ("JIRA", "jira:cloud:attachment:123", "", False),
        ("CONFLUENCE", "jira:cloud:attachment:123", "jira:cloud:issue:456", False),
        ("JIRA", "jira:cloud:attachment:123", "jira:cloud:attachment:456", False),
    ],
)
def test_delivery_attachment_requires_recorded_owner_in_same_cloud(
    provider, source, parent, accepted
):
    document = Document(
        page_content="Evidence",
        metadata={
            "source_type": "ATTACHMENT",
            "provider": provider,
            "source_id": source,
            "parent_issue_source_id": parent,
        },
    )
    generated = GroundedAnswer(answer="Evidence [SOURCE 1]", citations=[1])
    assert _source_authority_valid("DELIVERY", generated, [document])[0] is accepted
