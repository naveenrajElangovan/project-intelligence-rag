import json
from evaluation.audit_jira_status import audit


def test_correct_status_does_not_excuse_an_invented_priority_or_historical_citation():
    metadata = {
        "source_id": "jira:cloud:issue:1",
        "locator": "current:1",
        "jira_chunk_kind": "CURRENT",
        "title": "Example",
        "source_url": "https://jira.example/browse/OPS-1",
    }
    record = {
        "metadata": metadata,
        "document": "OPS-1: Example\nCurrent issue fields:\n"
        + json.dumps({"status": {"name": "Open"}, "priority": {"name": "High"}}),
    }
    case = {
        "id": "one",
        "expected_current_status": "Open",
        "gold_match": {
            "any_of": [
                {
                    "all_of": [
                        {"field": "source_id", "equals": metadata["source_id"]},
                        {"field": "locator", "equals": "current:1"},
                    ]
                }
            ]
        },
    }
    response = {
        "status": "ANSWERED",
        "answer": "The status of 'Example' is 'Open' with high priority.",
        "citations": [{"url": metadata["source_url"], "locator": "current:1"}],
    }
    results = {
        "run_id": "run",
        "status": "EXECUTION_COMPLETE_REVIEW_PENDING",
        "cases": [{"id": "one", "language": "en", "selected_hit": True, "response": response}],
    }
    assert audit(results, [case], [record])["accuracy"] == 1
    response["answer"] = response["answer"].replace("high", "medium")
    assert audit(results, [case], [record])["accuracy"] == 0
    response["answer"] = response["answer"].replace("medium", "high")
    response["citations"][0]["locator"] = "changelog:1"
    assert audit(results, [case], [record])["accuracy"] == 0
