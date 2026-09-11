import pytest
from evaluation.score_jira_review import score, response_hash


def fixture():
    body = {"answer": "Parent is OPS-1", "citations": [{"locator": "parent:1"}]}
    result = {
        "status": "EXECUTION_COMPLETE_REVIEW_PENDING",
        "expected_case_count": 1,
        "cases": [{"id": "one", "language": "en", "response": body}],
    }
    review = {
        "id": "one",
        "response_sha256": response_hash(body),
        "answer_or_abstention_correct": True,
        "citation_supported": [True],
        "rationale": "Related issue key matches the cited projection.",
    }
    return result, [review]


def test_rejects_missing_reviews_and_changed_responses():
    result, reviews = fixture()
    assert score(result, reviews)["citation_correctness"] == 1
    with pytest.raises(ValueError):
        score(result, [])
    result["cases"][0]["response"]["answer"] = "Different unsupported claim"
    with pytest.raises(ValueError, match="changed response"):
        score(result, reviews)


def test_failed_semantics_are_not_overridden_by_valid_citation_identity():
    result, reviews = fixture()
    reviews[0]["answer_or_abstention_correct"] = False
    reviews[0]["citation_supported"] = [False]
    measured = score(result, reviews)
    assert measured["grounded_answer_abstention_correctness"] == 0
    assert measured["citation_correctness"] == 0
