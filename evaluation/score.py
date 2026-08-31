"""Score captured evaluation results without sending content to another service."""

import argparse
import json
import math
from pathlib import Path

from app.config import Settings


def _dcg(values: list[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(values))


def score(
    rows: list[dict[str, object]],
    *,
    settings: Settings,
    project_id: str,
) -> dict[str, float | int]:
    answerable = [row for row in rows if row.get("answerable") is True]
    recalls, ndcgs = [], []
    resolved_gold_cases = 0
    answer_evidence_cases = 0
    leakage = 0
    for row in answerable:
        gold = set(row.get("gold_chunk_ids", []))
        retrieved = list(row.get("retrieved_chunk_ids", []))[
            : settings.retrieval_top_k
        ]
        reranked = list(row.get("reranked_chunk_ids", []))[:8]
        if gold:
            resolved_gold_cases += 1
            recalls.append(len(gold.intersection(retrieved)) / len(gold))
        if gold and row.get("role", "answer_evidence") == "answer_evidence":
            answer_evidence_cases += 1
            relevance = [int(item in gold) for item in reranked]
            ideal = [1] * min(len(gold), 8)
            ndcgs.append(_dcg(relevance) / _dcg(ideal))
        leakage += int(
            any(
                project != project_id
                for project in row.get("exposed_project_ids", [])
            )
        )
    surviving_gold_answers = sum(
        bool(row.get("answered"))
        for row in answerable
        if row.get("gold_chunk_ids")
        and row.get("role", "answer_evidence") == "answer_evidence"
    )
    return {
        "cases": len(rows),
        "recall_at_25": sum(recalls) / len(recalls) if recalls else 0,
        "ndcg_at_8": sum(ndcgs) / len(ndcgs) if ndcgs else 0,
        "gold_resolution_rate": (
            resolved_gold_cases / len(answerable) if answerable else 0
        ),
        "gold_survival_rate": (
            surviving_gold_answers / answer_evidence_cases if answer_evidence_cases else 0
        ),
        "cross_project_leakage": leakage,
    }


def score_generation(rows: list[dict[str, object]]) -> dict[str, float | int]:
    """Score only outcomes produced by generate, citation, and grounding gates."""

    answerable = [row for row in rows if row.get("answerable") is True]
    no_answer = [row for row in rows if row.get("answerable") is False]
    accepted = sum(bool(row.get("grounding_accepted")) for row in answerable)
    citations_valid = sum(int(row.get("valid_citation_count") or 0) for row in rows)
    citations_total = sum(len(row.get("cited_source_ids", [])) for row in rows)
    false_positives = sum(bool(row.get("answered")) for row in no_answer)
    true_refusals = sum(not bool(row.get("answered")) for row in no_answer)
    refusals = sum(not bool(row.get("answered")) for row in rows)
    reason_cases = [row for row in no_answer if row.get("expected_refusal_reason")]
    correct_reasons = sum(
        row.get("refusal_reason") == row.get("expected_refusal_reason")
        for row in reason_cases
    )
    paraphrase_groups: dict[object, set[tuple[object, ...]]] = {}
    for row in rows:
        group = row.get("paraphrase_group")
        if not group:
            continue
        paraphrase_groups.setdefault(group, set()).add(
            (
                bool(row.get("answered")),
                bool(row.get("grounding_accepted")),
                row.get("refusal_reason"),
            )
        )
    divergent_groups = sum(
        len(signatures) > 1 for signatures in paraphrase_groups.values()
    )
    return {
        "cases": len(rows),
        "grounding_acceptance_rate": accepted / len(answerable) if answerable else 0,
        "citation_precision": citations_valid / citations_total if citations_total else 0,
        "refusal_precision": true_refusals / refusals if refusals else 0,
        "no_answer_false_positive_rate": false_positives / len(no_answer) if no_answer else 0,
        "refusal_reason_accuracy": correct_reasons / len(reason_cases) if reason_cases else 0,
        "paraphrase_groups": len(paraphrase_groups),
        "paraphrase_divergent_groups": divergent_groups,
        "paraphrase_invariance_rate": (
            (len(paraphrase_groups) - divergent_groups) / len(paraphrase_groups)
            if paraphrase_groups
            else 0
        ),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("results", type=Path)
    parser.add_argument("--project-id", required=True)
    arguments = parser.parse_args()
    rows = [json.loads(line) for line in arguments.results.read_text(encoding="utf-8").splitlines() if line]
    print(
        json.dumps(
            score(rows, settings=Settings(), project_id=arguments.project_id),
            indent=2,
        )
    )
