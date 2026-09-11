"""Combine an explicit, response-bound semantic review with measured retrieval.

This module does not guess semantic labels from answer status or citations.
Every completed case must have a review for the exact response being scored.
"""

import hashlib
import json


def response_hash(response):
    return hashlib.sha256(
        json.dumps(response, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def score(results, reviews):
    rows = results["cases"]
    if (
        results.get("status") != "EXECUTION_COMPLETE_REVIEW_PENDING"
        or len(rows) != results["expected_case_count"]
    ):
        raise ValueError("Evaluation execution is incomplete")
    by_id = {row["id"]: row for row in reviews}
    if len(by_id) != len(reviews) or set(by_id) != {row["id"] for row in rows}:
        raise ValueError("Every case requires exactly one semantic review")
    correct = citations = supported = 0
    by_language = {}
    failures = []
    for row in rows:
        review = by_id[row["id"]]
        if review.get("response_sha256") != response_hash(row["response"]):
            raise ValueError("Review refers to a changed response: " + row["id"])
        labels = review.get("citation_supported")
        if (
            type(review.get("answer_or_abstention_correct")) is not bool
            or not review.get("rationale")
            or not isinstance(labels, list)
            or any(type(label) is not bool for label in labels)
            or len(labels) != len(row["response"].get("citations") or [])
        ):
            raise ValueError("Explicit semantic labels and rationale are required: " + row["id"])
        good = review["answer_or_abstention_correct"]
        correct += int(good)
        citations += len(labels)
        supported += sum(labels)
        lang = by_language.setdefault(row["language"], {"cases": 0, "correct": 0})
        lang["cases"] += 1
        lang["correct"] += int(good)
        if not good or not all(labels):
            failures.append(row["id"])
    return {
        "cases": len(rows),
        "correct_answers_or_abstentions": correct,
        "grounded_answer_abstention_correctness": correct / len(rows),
        "citation_count": citations,
        "supported_citations": supported,
        "citation_correctness": supported / citations if citations else None,
        "by_language": by_language,
        "failed_semantic_cases": failures,
        "method": "Explicit source comparison by Codex; response hashes bind each review. Not an independent human review.",
    }
