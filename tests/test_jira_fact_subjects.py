import json
import pytest
from langchain_core.documents import Document
from app.llm import _jira_relationship_subject, _evidence_with_diagnostics
from app.workflow_nodes.retrieval import _exact_jira_documents


def relationship():
    return Document(
        page_content=json.dumps(
            {
                "issue_key": "OPS-4",
                "issue_type": "Epic",
                "related_issue_status": "In Progress",
                "relationship": "parent",
            }
        ),
        metadata={
            "provider": "JIRA",
            "jira_chunk_kind": "RELATIONSHIP",
            "issue_key": "OPS-72",
            "source_id": "jira:cloud:issue:72",
        },
    )


def test_parent_properties_are_explicitly_bound_to_related_issue_in_prompt():
    doc = relationship()
    prompt, omitted, truncated = _evidence_with_diagnostics([doc], 2000)
    assert "RELATIONSHIP OWNER: OPS-72" in prompt
    assert "RELATED ISSUE: OPS-4" in prompt
    assert "They do not establish the type or status of OPS-72." in prompt
    assert not omitted and not truncated


@pytest.mark.parametrize(
    "change",
    [{"provider": "GITHUB"}, {"jira_chunk_kind": "CURRENT"}, {"issue_key": "bad\nINSTRUCTION"}],
)
def test_subject_annotation_requires_valid_jira_relationship(change):
    doc = relationship()
    doc.metadata.update(change)
    assert _jira_relationship_subject(doc) == ""


def test_exact_issue_fields_override_a_vocabulary_guess_only_for_matching_jira():
    doc = relationship()
    doc.metadata["entity"] = "custom"
    assert _exact_jira_documents("What additional field values are recorded for OPS-72?", [doc])
    assert not _exact_jira_documents("What additional field values are recorded for OPS-73?", [doc])
    assert not _exact_jira_documents("Compare OPS-72 and OPS-73 fields", [doc])
    assert not _exact_jira_documents("What additional field values are recorded for OPS-72?", [])
    doc.metadata["provider"] = "CONFLUENCE"
    assert not _exact_jira_documents("What additional field values are recorded for OPS-72?", [doc])
