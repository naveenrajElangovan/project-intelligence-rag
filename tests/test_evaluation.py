import runpy
import math
from pathlib import Path

from app.config import Settings
from evaluation.run_retrieval_eval import (
    _generation_sample,
    _gold_ids,
    _load_evaluation_cases,
    _stratified_sample,
    _validate_gold_resolution,
)
from evaluation.score import score, score_generation


EVALUATION = Path(__file__).parents[1] / "evaluation"


def test_t2_dataset_has_all_80_curated_bilingual_cases() -> None:
    module = runpy.run_path(str(EVALUATION / "build_t2_dataset.py"))
    rows = module["build"]("DEMO")
    assert len(rows) == 80
    assert sum(row["query_language"] == "en" for row in rows) == 40
    assert sum(row["query_language"] == "es" for row in rows) == 40
    assert sum(not row["answerable"] for row in rows) == 20
    assert all(row["curation_status"] == "CURATED" for row in rows)
    assert all(row.get("gold_match") for row in rows if row["answerable"])


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


def test_gold_predicates_support_language_specific_all_of_matches() -> None:
    manifest = {
        "english": {
            "title": "Contract",
            "structure_path": '["POS_START_SHIFT"]',
            "source_id": "page:1",
            "doc_category": "entity-contract",
        },
        "spanish": {
            "title": "Contrato Spanish",
            "structure_path": '["POS_START_SHIFT — id 103, versión 0.2"]',
            "source_id": "page:2",
            "doc_category": "entity-contract",
        },
    }
    case = {
        "gold_match": {
            "any_of": [
                {
                    "all_of": [
                        {"field": "title", "equals": "Contrato Spanish"},
                        {"field": "structure_path", "contains": "POS_START_SHIFT"},
                    ]
                }
            ]
        }
    }

    assert _gold_ids(case, manifest) == ["spanish"]


def test_gold_contains_tolerates_ingestion_section_path_punctuation() -> None:
    manifest = {
        "chunk": {
            "title": "Workflow",
            "structure_path": '["BOTFLOW-040"]',
            "source_id": "page:1",
            "doc_category": "workflow",
        }
    }
    case = {
        "gold_match": {
            "any_of": [
                {"field": "structure_path", "contains": "[BOTFLOW-040]"}
            ]
        }
    }

    assert _gold_ids(case, manifest) == ["chunk"]


def test_unresolved_gold_is_a_hard_preflight_failure() -> None:
    cases = [
        {
            "id": "resolved",
            "answerable": True,
            "gold_match": {"any_of": [{"field": "title", "equals": "Present"}]},
        },
        {
            "id": "missing",
            "answerable": True,
            "gold_match": {"any_of": [{"field": "title", "equals": "Absent"}]},
        },
    ]
    manifest = {
        "chunk": {
            "title": "Present",
            "structure_path": "",
            "source_id": "page:1",
            "doc_category": "narrative",
        }
    }

    try:
        _validate_gold_resolution(cases, manifest, minimum_rate=0.95)
    except ValueError as error:
        assert "missing" in str(error)
        assert "0.500" in str(error)
    else:
        raise AssertionError("unresolved gold must fail the evaluation preflight")


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


def test_metrics_are_split_by_query_language() -> None:
    settings = Settings(_env_file=None, retrieval_top_k=25, rerank_top_n=8)
    rows = [
        {
            "query_language": "en",
            "answerable": True,
            "answered": True,
            "gold_chunk_ids": ["gold"],
            "retrieved_chunk_ids": ["gold"],
            "reranked_chunk_ids": ["gold"],
            "exposed_project_ids": ["T2.0"],
        },
        {
            "query_language": "es",
            "answerable": True,
            "answered": False,
            "gold_chunk_ids": ["gold"],
            "retrieved_chunk_ids": [],
            "reranked_chunk_ids": [],
            "exposed_project_ids": ["T2.0"],
        },
    ]

    summary = score(rows, settings=settings, project_id="T2.0")

    assert summary["by_query_language"]["en"]["ndcg_at_8"] == 1
    assert summary["by_query_language"]["es"]["ndcg_at_8"] == 0


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


def test_default_suite_has_bilingual_fast_lane_and_negative_reasons() -> None:
    cases = _load_evaluation_cases(EVALUATION / "gold_suites.jsonl")
    fast_lane = [case for case in cases if case.get("evaluation_lane") != "generation"]
    negatives = [case for case in cases if case.get("answerable") is False]
    sample = _stratified_sample(cases, 30)

    assert len(fast_lane) == 378
    assert len(negatives) == 40
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
    cases = _load_evaluation_cases(EVALUATION / "gold_suites.jsonl")
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
    assert {case.get("query_language") for case in sample} >= {"en", "es"}
