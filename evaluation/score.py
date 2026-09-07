"""Score captured evaluation results without sending content to another service."""

import argparse
import json
import math
from pathlib import Path

from app.config import Settings


GENERATION_DASHBOARD_METRICS = (
    "grounding_acceptance_rate",
    "citation_precision",
    "refusal_precision",
    "no_answer_false_positive_rate",
    "refusal_reason_accuracy",
    "paraphrase_invariance_rate",
)


def retrieval_dashboard_metrics(summary: dict[str, object]) -> tuple[str, ...]:
    retrieval_k = int(summary.get("retrieval_top_k", 25))
    rerank_k = int(summary.get("rerank_top_n", 8))
    return (
        f"precision_at_{rerank_k}",
        f"recall_at_{retrieval_k}",
        f"hit_rate_at_{rerank_k}",
        f"mrr_at_{rerank_k}",
        f"ndcg_at_{rerank_k}",
    )


def _dcg(values: list[int]) -> float:
    return sum(value / math.log2(index + 2) for index, value in enumerate(values))


def score(
    rows: list[dict[str, object]],
    *,
    settings: Settings,
    project_id: str,
    _include_language_splits: bool = True,
) -> dict[str, object]:
    answerable = [row for row in rows if row.get("answerable") is True]
    retrieval_k = settings.retrieval_top_k
    rerank_k = settings.rerank_top_n
    precision_name, recall_name, hit_rate_name, mrr_name, ndcg_name = (
        retrieval_dashboard_metrics(
            {"retrieval_top_k": retrieval_k, "rerank_top_n": rerank_k}
        )
    )
    precisions, recalls, hit_rates, reciprocal_ranks, ndcgs = [], [], [], [], []
    resolved_gold_cases = 0
    answer_evidence_cases = 0
    leakage = 0
    for row in answerable:
        gold = set(row.get("gold_chunk_ids", []))
        retrieved = list(row.get("retrieved_chunk_ids", []))[
            : settings.retrieval_top_k
        ]
        reranked = list(row.get("reranked_chunk_ids", []))[:rerank_k]
        if gold:
            resolved_gold_cases += 1
            recalls.append(len(gold.intersection(retrieved)) / len(gold))
        if gold and row.get("role", "answer_evidence") == "answer_evidence":
            answer_evidence_cases += 1
            relevance = [int(item in gold) for item in reranked]
            relevant_count = sum(relevance)
            precisions.append(relevant_count / rerank_k)
            hit_rates.append(float(relevant_count > 0))
            reciprocal_ranks.append(
                next(
                    (1 / rank for rank, relevant in enumerate(relevance, 1) if relevant),
                    0.0,
                )
            )
            ideal = [1] * min(len(gold), rerank_k)
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
    summary: dict[str, object] = {
        "cases": len(rows),
        "answerable_cases": len(answerable),
        "gold_resolved_cases": resolved_gold_cases,
        "answer_evidence_cases": answer_evidence_cases,
        "retrieval_top_k": retrieval_k,
        "rerank_top_n": rerank_k,
        precision_name: sum(precisions) / len(precisions) if precisions else 0,
        recall_name: sum(recalls) / len(recalls) if recalls else 0,
        hit_rate_name: sum(hit_rates) / len(hit_rates) if hit_rates else 0,
        mrr_name: (
            sum(reciprocal_ranks) / len(reciprocal_ranks)
            if reciprocal_ranks
            else 0
        ),
        ndcg_name: sum(ndcgs) / len(ndcgs) if ndcgs else 0,
        "gold_resolution_rate": (
            resolved_gold_cases / len(answerable) if answerable else 0
        ),
        "gold_survival_rate": (
            surviving_gold_answers / answer_evidence_cases if answer_evidence_cases else 0
        ),
        "cross_project_leakage": leakage,
    }
    languages = sorted(
        {str(row.get("query_language") or "und") for row in rows}
    )
    if _include_language_splits and languages != ["und"]:
        by_language = {
            language: score(
                [
                    row
                    for row in rows
                    if str(row.get("query_language") or "und") == language
                ],
                settings=settings,
                project_id=project_id,
                _include_language_splits=False,
            )
            for language in languages
        }
        summary["by_query_language"] = by_language
        if "en" in by_language and "es" in by_language:
            metrics = retrieval_dashboard_metrics(summary)
            summary["language_gap"] = {
                name: float(by_language["en"][name]) - float(by_language["es"][name])
                for name in metrics
            }
            summary["language_gap_abs"] = {
                name: abs(float(by_language["en"][name]) - float(by_language["es"][name]))
                for name in metrics
            }
    return summary


def retrieval_dashboard_scores(summary: dict[str, object]) -> dict[str, float]:
    """Flatten safe aggregate retrieval scores into Phoenix annotation names."""

    result: dict[str, float] = {}
    languages = summary.get("by_query_language", {})
    gaps = summary.get("language_gap", {})
    absolute_gaps = summary.get("language_gap_abs", {})
    for name in retrieval_dashboard_metrics(summary):
        result[f"{name}.overall"] = float(summary.get(name, 0.0))
        if isinstance(languages, dict):
            for language in ("en", "es"):
                values = languages.get(language)
                if isinstance(values, dict) and name in values:
                    result[f"{name}.{language}"] = float(values[name])
        if isinstance(gaps, dict) and name in gaps:
            result[f"{name}.language_gap"] = float(gaps[name])
        if isinstance(absolute_gaps, dict) and name in absolute_gaps:
            result[f"{name}.language_gap_abs"] = float(absolute_gaps[name])
    return result


def retrieval_dashboard_sample_counts(summary: dict[str, object]) -> dict[str, int]:
    """Return the population denominator used by each flattened retrieval score."""

    metrics = retrieval_dashboard_metrics(summary)
    recall_name = metrics[1]
    result: dict[str, int] = {}
    language_values = summary.get("by_query_language", {}) or {}
    populations = [("overall", summary)]
    if isinstance(language_values, dict):
        populations.extend(language_values.items())
    for suffix, values in populations:
        if not isinstance(values, dict):
            continue
        for name in metrics:
            population = (
                "gold_resolved_cases"
                if name == recall_name
                else "answer_evidence_cases"
            )
            result[f"{name}.{suffix}"] = int(values.get(population, 0))
    for name in metrics:
        population = (
            "gold_resolved_cases" if name == recall_name else "answer_evidence_cases"
        )
        result[f"{name}.language_gap"] = int(summary.get(population, 0))
        result[f"{name}.language_gap_abs"] = int(summary.get(population, 0))
    return result


def score_generation(
    rows: list[dict[str, object]], *, _include_language_splits: bool = True
) -> dict[str, object]:
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
    summary: dict[str, object] = {
        "cases": len(rows),
        "answerable_cases": len(answerable),
        "no_answer_cases": len(no_answer),
        "citation_count": citations_total,
        "refusal_cases": refusals,
        "refusal_reason_cases": len(reason_cases),
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
    languages = sorted(
        {str(row.get("query_language") or "und") for row in rows}
    )
    if _include_language_splits and languages != ["und"]:
        by_language = {
            language: score_generation(
                [
                    row
                    for row in rows
                    if str(row.get("query_language") or "und") == language
                ],
                _include_language_splits=False,
            )
            for language in languages
        }
        summary["by_query_language"] = by_language
        if "en" in by_language and "es" in by_language:
            summary["language_gap"] = {
                name: float(by_language["en"][name]) - float(by_language["es"][name])
                for name in GENERATION_DASHBOARD_METRICS
            }
            summary["language_gap_abs"] = {
                name: abs(float(by_language["en"][name]) - float(by_language["es"][name]))
                for name in GENERATION_DASHBOARD_METRICS
            }
    return summary


def generation_dashboard_scores(summary: dict[str, object]) -> dict[str, float]:
    """Flatten deterministic generation diagnostics into Phoenix annotation names."""

    result: dict[str, float] = {}
    languages = summary.get("by_query_language", {})
    gaps = summary.get("language_gap", {})
    absolute_gaps = summary.get("language_gap_abs", {})
    for name in GENERATION_DASHBOARD_METRICS:
        result[f"{name}.overall"] = float(summary.get(name, 0.0))
        if isinstance(languages, dict):
            for language in ("en", "es"):
                values = languages.get(language)
                if isinstance(values, dict) and name in values:
                    result[f"{name}.{language}"] = float(values[name])
        if isinstance(gaps, dict) and name in gaps:
            result[f"{name}.language_gap"] = float(gaps[name])
        if isinstance(absolute_gaps, dict) and name in absolute_gaps:
            result[f"{name}.language_gap_abs"] = float(absolute_gaps[name])
    return result


def generation_dashboard_sample_counts(summary: dict[str, object]) -> dict[str, int]:
    """Return the actual population behind each deterministic generation metric."""

    population_by_metric = {
        "grounding_acceptance_rate": "answerable_cases",
        "citation_precision": "citation_count",
        "refusal_precision": "refusal_cases",
        "no_answer_false_positive_rate": "no_answer_cases",
        "refusal_reason_accuracy": "refusal_reason_cases",
        "paraphrase_invariance_rate": "paraphrase_groups",
    }
    result: dict[str, int] = {}
    language_values = summary.get("by_query_language", {}) or {}
    populations = [("overall", summary)]
    if isinstance(language_values, dict):
        populations.extend(language_values.items())
    for suffix, values in populations:
        if not isinstance(values, dict):
            continue
        for name, population in population_by_metric.items():
            result[f"{name}.{suffix}"] = int(values.get(population, 0))
    for name, population in population_by_metric.items():
        result[f"{name}.language_gap"] = int(summary.get(population, 0))
        result[f"{name}.language_gap_abs"] = int(summary.get(population, 0))
    return result


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
