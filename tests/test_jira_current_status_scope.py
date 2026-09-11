from app.workflow_support.deterministic_answers import _deterministic_delivery_answer
import pytest
from langchain_core.documents import Document
from app.jira_query import current_jira_status_evidence, jira_current_status_question


def docs():
    return [
        Document(
            page_content="Current status: Open",
            metadata={"provider": "JIRA", "jira_chunk_kind": "CURRENT"},
        ),
        Document(
            page_content="Changed status from Open to Done",
            metadata={"provider": "JIRA", "jira_chunk_kind": "CHANGELOG"},
        ),
        Document(
            page_content="Retrospective status Done",
            metadata={"provider": "JIRA", "jira_chunk_kind": "COMMENT"},
        ),
        Document(page_content="Legacy unclassified issue", metadata={"provider": "JIRA"}),
        Document(page_content="Other-provider state", metadata={"provider": "GITHUB"}),
    ]


@pytest.mark.parametrize(
    "question",
    [
        "Compare the current statuses of OPS-1 and HELP-72",
        "¿Cuáles son los estados actuales de OPS-1 y HELP-72?",
        "List current Jira statuses",
    ],
)
def test_bulk_current_status_never_uses_jira_history_or_unclassified_legacy_chunks(question):
    values = docs()
    assert jira_current_status_question(question)
    assert current_jira_status_evidence(question, values, "DELIVERY") == [values[0], values[-1]]


@pytest.mark.parametrize(
    "question",
    [
        "What were the previous statuses of OPS-1 and HELP-72?",
        "¿Cuáles eran los estados anteriores de OPS-1?",
        "What status is mentioned in comment 123 of OPS-1?",
        "What is the status of the parent of OPS-1?",
    ],
)
def test_explicit_history_and_related_record_status_keep_their_evidence(question):
    values = docs()
    assert current_jira_status_evidence(question, values, "DELIVERY") == values


def test_non_delivery_status_questions_keep_other_ingestion_behavior():
    values = docs()
    assert (
        current_jira_status_evidence(
            "What is the status enum implementation?", values, "CODE_ASSISTED"
        )
        == values
    )




def current(key, status):
    return Document(
        page_content=f"{key}: {status}",
        metadata={
            "provider": "JIRA",
            "source_type": "ISSUE",
            "jira_chunk_kind": "CURRENT",
            "issue_key": key,
            "status": status,
            "source_id": "jira:cloud:" + key,
        },
    )


@pytest.mark.parametrize("lang", ["en", "es"])
def test_multi_issue_status_is_complete_and_separately_cited(lang):
    answer = _deterministic_delivery_answer(
        "Compare current statuses of OPS-8 and HELP-99",
        [current("HELP-99", "In Review"), current("OPS-8", "Done")],
        lang,
    )
    assert "OPS-8:" in answer.answer and "Done [SOURCE 2]" in answer.answer
    assert "HELP-99:" in answer.answer and "In Review [SOURCE 1]" in answer.answer
    assert answer.citations == [2, 1]


@pytest.mark.parametrize("mode", ["missing", "duplicate", "history"])
def test_multi_issue_status_does_not_render_incomplete_or_ambiguous_evidence(mode):
    documents = [current("OPS-8", "Done"), current("HELP-99", "Open")]
    if mode == "missing":
        documents.pop()
    if mode == "duplicate":
        documents.append(current("OPS-8", "Other"))
    if mode == "history":
        documents[1].metadata["jira_chunk_kind"] = "CHANGELOG"
    assert (
        _deterministic_delivery_answer("Compare statuses of OPS-8 and HELP-99", documents, "en")
        is None
    )


def test_same_application_multi_issue_match_outranks_a_guessed_project_prefix():
    from app.workflow_nodes.retrieval import _exact_jira_documents

    values = [current("OPS-8", "Done"), current("OPS-9", "Open")]
    for value in values:
        value.metadata["entity"] = "pos"
    assert _exact_jira_documents("Compare statuses of OPS-8 and OPS-9", values)
    values[1].metadata["jira_chunk_kind"] = "CHANGELOG"
    assert not _exact_jira_documents("Compare statuses of OPS-8 and OPS-9", values)
