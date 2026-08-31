import runpy
import math
from pathlib import Path

from app.config import Settings
from evaluation.run_retrieval_eval import (
    _generation_sample,
    _load_jsonl,
    _stratified_sample,
)
from evaluation.score import score, score_generation


EVALUATION = Path(__file__).parents[1] / "evaluation"


def test_t2_dataset_has_all_80_bilingual_security_cases() -> None:
    module = runpy.run_path(str(EVALUATION / "build_t2_dataset.py"))
    rows = module["build"]("DEMO")
    assert len(rows) == 80
    assert {row["query_language"] for row in rows} >= {"en", "es"}
    assert sum(not row["answerable"] for row in rows) == 20


def test_threshold_calibration_respects_five_percent_limit() -> None:
    module = runpy.run_path(str(EVALUATION / "calibrate_threshold.py"))
    rows = [{"answerable": False, "max_rerank_score": value / 100} for value in range(20)]
    threshold = module["calibrate"](rows)
    false_positive_rate = sum(row["max_rerank_score"] >= threshold for row in rows) / len(rows)
    assert false_positive_rate <= 0.05


def test_score_uses_configured_retrieval_pool_fixed_ndcg_window_and_project_boundary() -> None:
    settings = Settings(
        _env_file=None,
        environment="development",
        retrieval_top_k=1,
        rerank_top_n=1,
    )
    summary = score(
        [
            {
                "answerable": True,
                "answered": True,
                "gold_chunk_ids": ["gold"],
                "retrieved_chunk_ids": ["miss", "gold"],
                "reranked_chunk_ids": ["miss", "gold"],
                "exposed_project_ids": ["other-project"],
            }
        ],
        settings=settings,
        project_id="expected-project",
    )

    assert summary["recall_at_25"] == 0
    assert math.isclose(summary["ndcg_at_8"], 1 / math.log2(3))
    assert summary["cross_project_leakage"] == 1


def test_generation_metrics_are_separate_from_retrieval_survival() -> None:
    summary = score_generation(
        [
            {
                "answerable": True,
                "answered": True,
                "grounding_accepted": True,
                "cited_source_ids": ["page:1"],
                "valid_citation_count": 1,
            },
            {
                "answerable": False,
                "answered": False,
                "expected_refusal_reason": "INSUFFICIENT_EVIDENCE",
                "refusal_reason": "INSUFFICIENT_EVIDENCE",
                "cited_source_ids": [],
                "valid_citation_count": 0,
            },
        ]
    )

    assert summary["grounding_acceptance_rate"] == 1
    assert summary["citation_precision"] == 1
    assert summary["refusal_precision"] == 1
    assert summary["refusal_reason_accuracy"] == 1


def test_generation_metrics_report_paraphrase_divergence() -> None:
    rows = [
        {
            "answerable": True,
            "answered": answered,
            "grounding_accepted": answered,
            "paraphrase_group": "same_need",
            "cited_source_ids": [],
        }
        for answered in (True, False)
    ]

    summary = score_generation(rows)

    assert summary["paraphrase_groups"] == 1
    assert summary["paraphrase_divergent_groups"] == 1
    assert summary["paraphrase_invariance_rate"] == 0


def test_fast_lane_stays_318_cases_and_generation_sample_covers_negative_reasons() -> None:
    cases = _load_jsonl(EVALUATION / "gold_suites.jsonl")
    fast_lane = [case for case in cases if case.get("evaluation_lane") != "generation"]
    negatives = [case for case in cases if case.get("answerable") is False]
    sample = _stratified_sample(cases, 30)

    assert len(fast_lane) == 318
    assert len(negatives) == 20
    assert {
        case.get("expected_refusal_reason")
        for case in sample
        if case.get("answerable") is False
    } == {
        "INSUFFICIENT_EVIDENCE",
        "UNVERIFIED_EVIDENCE",
        "POPULATION_RETRIEVAL_MISS",
    }


def test_generation_sample_always_includes_every_paraphrase_case() -> None:
    cases = _load_jsonl(EVALUATION / "gold_suites.jsonl")
    sample = _generation_sample(cases, 30)

    paraphrases = [case for case in sample if case.get("paraphrase_group")]
    assert len(sample) == 30
    assert len(paraphrases) == 20
    assert {case["paraphrase_group"] for case in paraphrases} == {
        "named_member",
        "pos_event_inventory",
        "entity_behavior",
        "cross_source",
    }
