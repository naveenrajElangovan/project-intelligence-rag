import pytest
from langchain_core.documents import Document

from app.retrieval_pipeline import deduplicate_candidate_bodies
from app.workflow_support.deterministic_answers import _deterministic_delivery_answer


def issue(kind="CURRENT"):
    return Document(
        page_content="T0-12 payment",
        metadata={
            "provider": "JIRA",
            "source_type": "ISSUE",
            "issue_key": "T0-12",
            "title": "Payment",
            "status": "In Review",
            "jira_chunk_kind": kind,
        },
    )


@pytest.mark.parametrize(
    "question",
    [
        "What was T0-12's previous status?",
        "Why did the status of T0-12 change?",
        "¿Cuál era el estado anterior de T0-12?",
        "When did T0-12 change status?",
    ],
)
def test_historical_questions_cannot_use_current_state_shortcut(question):
    assert _deterministic_delivery_answer(question, [issue()], "en") is None


def test_current_status_requires_current_evidence():
    assert (
        _deterministic_delivery_answer("What is the status of T0-12?", [issue()], "en") is not None
    )
    assert (
        _deterministic_delivery_answer("What is the status of T0-12?", [issue("COMMENT")], "en")
        is None
    )


def test_deduplication_preserves_different_issue_and_event_identities():
    docs = [
        Document(
            page_content="Repeated text",
            metadata={
                "provider": "JIRA",
                "source_id": source,
                "locator": locator,
                "content_hash": "same",
            },
        )
        for source, locator in [
            ("issue:1", "comment:1"),
            ("issue:2", "comment:1"),
            ("issue:1", "comment:2"),
        ]
    ]
    assert len(deduplicate_candidate_bodies(docs)) == 3


@pytest.mark.parametrize(
    "question", ["What is the current status of OPS-72?", "¿Cuál es el estado actual de OPS-72?"]
)
def test_exact_current_issue_survives_related_and_historical_candidates(question):
    from app.workflow_support.deterministic_answers import exact_current_issue_evidence

    target = issue()
    target.metadata.update(issue_key="OPS-72", source_id="jira:cloud:issue:72")
    other = issue()
    other.metadata.update(source_id="jira:cloud:issue:12")
    history = issue("CHANGELOG")
    history.metadata.update(issue_key="OPS-72", source_id="jira:cloud:issue:72")
    assert exact_current_issue_evidence(question, [other, history, target]) == [target]
    assert exact_current_issue_evidence("What was OPS-72 previous status?", [target]) == []
    ambiguous = Document(
        page_content=target.page_content,
        metadata={**target.metadata, "source_id": "jira:othercloud:issue:72"},
    )
    assert exact_current_issue_evidence(question, [target, ambiguous]) == []


def test_exact_lookup_keeps_current_issue_when_many_related_chunks_match():
    from app.retrieval import ChromaAccessRetriever
    from unittest.mock import Mock

    rows = []
    for i in range(25):
        rows.append(
            {
                "project_id": "OTHER",
                "access_policy_id": "project:OTHER",
                "source_id": f"jira:cloud:issue:{i}",
                "source_type": "ISSUE",
                "issue_key": f"OPS-{100 + i}",
                "jira_chunk_kind": "COMMENT",
                "title": "OPS-72 referenced",
            }
        )
    rows.append(
        {
            **rows[0],
            "source_id": "jira:cloud:issue:72",
            "issue_key": "OPS-72",
            "jira_chunk_kind": "CURRENT",
            "title": "Target issue",
        }
    )
    index = Mock()
    index.get.return_value = {
        "ids": [str(i) for i in range(26)],
        "documents": ["OPS-72 reference"] * 25 + ["Current status: Done"],
        "metadatas": rows,
    }
    retriever = ChromaAccessRetriever(
        index=index,
        collection_name="generic",
        project_id="OTHER",
        access_policy_ids=("project:OTHER",),
    )
    docs = retriever._exact_identifier_documents(("OPS-72",), ("ISSUE",))
    assert docs[0].metadata["issue_key"] == "OPS-72"
    assert docs[0].metadata["jira_chunk_kind"] == "CURRENT"
    assert len(docs) == 12
    for call in index.get.call_args_list:
        assert {"project_id": {"$eq": "OTHER"}} in call.kwargs["where"]["$and"]


def test_final_citations_preserve_jira_sections_and_existing_non_jira_grouping():
    from app.workflow_support.query_analysis import _dedupe_source_documents

    docs = [
        Document(
            page_content="Source section",
            metadata={
                "provider": "JIRA",
                "source_type": "ISSUE",
                "reference": "OPS-72",
                "source_id": "jira:cloud:72",
                "source_url": "https://jira.test/browse/OPS-72",
                "locator": locator,
            },
        )
        for locator in ["description:1", "description:2", "description:1"]
    ]
    assert [d.metadata["locator"] for d in _dedupe_source_documents(docs)] == [
        "description:1",
        "description:2",
    ]
    pages = [
        Document(
            page_content=d.page_content,
            metadata={**d.metadata, "provider": "CONFLUENCE", "source_type": "PAGE"},
        )
        for d in docs
    ]
    assert len(_dedupe_source_documents(pages)) == 1
