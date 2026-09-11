from evaluation.audit_jira_results import audit


def test_citation_identity_is_not_treated_as_semantic_correctness():
    case = {
        "id": "x",
        "answerable": True,
        "gold_match": {
            "any_of": [
                {
                    "all_of": [
                        {"field": "source_id", "equals": "s"},
                        {"field": "locator", "equals": "current:1"},
                    ]
                }
            ]
        },
    }
    record = {
        "metadata": {
            "source_id": "s",
            "locator": "current:1",
            "source_url": "https://example.test/browse/OPS-1",
        }
    }
    row = {
        "id": "x",
        "language": "en",
        "suite": "jira_current",
        "candidate_hit": True,
        "selected_hit": True,
        "response": {
            "status": "ANSWERED",
            "answer": "an incorrect assertion",
            "citations": [{"url": "https://example.test/browse/OPS-1", "locator": "current:1"}],
            "evaluationEvidence": {
                "candidates": [{"project_id": "OTHER", "access_policy_id": "project:OTHER"}]
            },
        },
    }
    run = {
        "run_id": "r",
        "project_id": "OTHER",
        "status": "EXECUTION_COMPLETE_REVIEW_PENDING",
        "cases": [row],
    }
    measured = audit(run, [case], [record])
    assert measured["final_evidence_recall"] == 1
    assert measured["citation_identity_correctness"] == 1
    assert measured["grounded_answer_accuracy"] is None
    assert measured["citation_semantic_correctness"] is None
    row["response"]["citations"][0]["url"] = "https://unrelated.test"
    row["response"]["evaluationEvidence"]["candidates"][0]["project_id"] = "UNAUTHORIZED"
    measured = audit(run, [case], [record])
    assert measured["final_evidence_recall"] == 0
    assert measured["citation_identity_correctness"] == 0
    assert measured["unauthorized_captured_identities"] == 1
