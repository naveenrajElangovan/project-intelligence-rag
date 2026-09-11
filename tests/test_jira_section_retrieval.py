from unittest.mock import Mock
import pytest
from app.jira_query import jira_section_query
from app.retrieval import ChromaAccessRetriever


@pytest.mark.parametrize(
    "question,kind,event",
    [
        ("What behavior is described in OPS-72?", "DESCRIPTION", None),
        ("¿Qué comportamiento describe OPS-72?", "DESCRIPTION", None),
        ("What does comment 123 on OPS-72 say?", "COMMENT", "123"),
        ("¿Qué cambió en el evento histórico 999 de OPS-72?", "CHANGELOG", "999"),
        ("What was the previous status of OPS-72?", "CHANGELOG", None),
        ("¿Cuál es el estado actual de OPS-72?", "CURRENT", None),
        ("What evidence does attachment dossier.md on OPS-72 contain?", "ATTACHMENT", None),
        ("What acceptance criteria are documented for OPS-72?", "ACCEPTANCE", None),
        ("What does worklog 456 on OPS-72 say?", "WORKLOG", "456"),
        ("How does OPS-72 define settlement?", "GLOSSARY", None),
        ("¿Qué referencia externa está vinculada a OPS-72?", "REMOTE_LINK", None),
    ],
)
def test_generic_bilingual_section_routing(question, kind, event):
    assert jira_section_query(question) == ("OPS-72", kind, event)


def test_multiple_issues_or_plain_code_query_not_forced_into_single_issue():
    assert jira_section_query("Compare OPS-72 and OTHER-19 status") is None
    assert jira_section_query("How does POS_START_SHIFT work?") is None


def test_section_reads_keep_authorization_and_event_filters():
    index = Mock()
    index.get.return_value = {"ids": [], "documents": [], "metadatas": []}
    retriever = ChromaAccessRetriever(
        index=index,
        collection_name="generic",
        project_id="OTHER",
        access_policy_ids=("project:OTHER",),
    )
    assert retriever._jira_section_documents("What does comment 123 on OPS-72 say?") == []
    filters = index.get.call_args.kwargs["where"]["$and"]
    assert {"project_id": {"$eq": "OTHER"}} in filters
    assert {"access_policy_id": {"$eq": "project:OTHER"}} in filters
    assert {"issue_key": "OPS-72"} in filters
    assert {"event_id": "123"} in filters
    assert {"jira_chunk_kind": "COMMENT"} in filters
    assert {"provider": "JIRA"} in filters
    assert index.get.call_args.kwargs["limit"] == 64
