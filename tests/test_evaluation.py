import runpy
import hashlib
import json
import math
import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.models import RagResponse, RetrievalProfile
from app.workflow import AuthorizedRagWorkflow
from langchain_core.documents import Document
from evaluation.run_retrieval_eval import (
    _MINIMUM_GOLD_RESOLUTION_RATE,
    _RecordedCandidateWorkflow,
    _apply_reviewed_references,
    _generation_candidate_rows,
    _reviewed_bilingual_ragas_cases,
    _generation_sample,
    _gold_ids,
    _load_evaluation_cases,
    _rehydrate_recorded_candidates,
    _run_generation_lane,
    _stratified_sample,
    _validate_gold_resolution,
)
from evaluation.score import (
    generation_dashboard_scores,
    generation_dashboard_sample_counts,
    retrieval_dashboard_sample_counts,
    retrieval_dashboard_scores,
    score,
    score_generation,
)
from evaluation.build_bilingual_reference_template import build as build_reference_template
from evaluation.build_gold_suites import build_registered_suites, build_store_canonical_suite


EVALUATION = Path(__file__).parents[1] / "evaluation"
STORE_DOCS = Path(__file__).parents[1] / "docs" / "store-assistant"


def test_project_retrieval_profile_can_lower_only_the_rerank_filter() -> None:
    profile = RetrievalProfile(
        maxChunksPerSource=6,
        rerankTopN=16,
        mixedSourceTopN=12,
        rerankScoreThreshold=0.0,
    )

    assert profile.settings_overrides() == {
        "max_chunks_per_source": 6,
        "rerank_top_n": 16,
        "mixed_source_top_n": 12,
        "rerank_score_threshold": 0.0,
    }


def test_evaluation_interface_captures_exact_final_evidence(monkeypatch) -> None:
    response = RagResponse(
        answer="Grounded answer",
        status="ANSWERED",
        confidence="HIGH",
        projectId="T2.0",
        sources=[],
        missingInformation=[],
    )
    state = {
        "language": "es",
        "documents": [Document(page_content="evidencia", metadata={})],
        "answer_style": "direct",
        "context_relevance": 0.42,
        "answer_relevance": 0.73,
        "pre_gate_draft_answer": "Draft answer [SOURCE 1]",
        "answer_relevance_scorer_question": "resolved question",
        "answer_relevance_scorer_answer": "Draft answer",
    }
    workflow = object.__new__(AuthorizedRagWorkflow)
    workflow._request = SimpleNamespace(question="pregunta", project_id="T2.0")
    workflow._settings = SimpleNamespace(max_retrieval_attempts=2)
    workflow._vocabulary = SimpleNamespace(entities=(), source_types=())
    workflow._graph = object()

    async def invoke(*_args, **_kwargs):
        return state

    async def response_from_state(actual_state, _began):
        assert actual_state is state
        return response

    monkeypatch.setattr("app.workflow_evaluation.invoke_bounded_graph", invoke)
    monkeypatch.setattr("app.workflow_evaluation.json_transform_response", lambda *_: None)
    monkeypatch.setattr("app.workflow_evaluation.clarification_response", lambda *_: None)
    monkeypatch.setattr(workflow, "_response_from_state", response_from_state)
    evaluated = asyncio.run(workflow.run_for_evaluation())
    assert evaluated.response is response
    assert evaluated.retrieved_contexts == ("evidencia",)
    assert evaluated.query_language == "es"
    assert evaluated.answer_style == "direct"
    assert evaluated.context_relevance == 0.42
    assert evaluated.answer_relevance == 0.73
    assert evaluated.pre_gate_draft_answer == "Draft answer [SOURCE 1]"
    assert evaluated.answer_relevance_scorer_question == "resolved question"
    assert evaluated.answer_relevance_scorer_answer == "Draft answer"


def test_quality_monitoring_does_not_change_runtime_gates() -> None:
    settings = Settings(_env_file=None, environment="development")
    assert settings.rerank_score_threshold == 0.10
    assert settings.rerank_cross_language_score_threshold == 0.05
    assert settings.grounding_score_threshold == 0.65
    assert settings.grounding_cross_language_score_threshold == 0.60
    assert settings.grounding_table_evidence_score_threshold == 0.60
    assert _MINIMUM_GOLD_RESOLUTION_RATE == 0.95


def test_store_canonical_suite_has_184_cases_per_language() -> None:
    cases = build_store_canonical_suite(
        STORE_DOCS / "en/topics/10_CANONICAL_QUESTION_INDEX.md",
        STORE_DOCS / "es/topics/10_INDICE_DE_PREGUNTAS_CANONICAS.md",
    )
    assert len(cases) == 368
    assert sum(case["query_language"] == "en" for case in cases) == 184
    assert sum(case["query_language"] == "es" for case in cases) == 184
    assert {case["project_id"] for case in cases} == {"T2.0-STORE"}
    assert all(case["gold_match"]["any_of"] for case in cases)
    assert all(
        predicate["field"] == "structure_path"
        and predicate["contains"].startswith("[")
        for case in cases
        for predicate in case["gold_match"]["any_of"]
    )


def test_ninth_department_suite_is_registry_only_configuration(tmp_path) -> None:
    registry = tmp_path / "suites.json"
    registry.write_text(
        json.dumps(
            {
                "suites": [
                    {
                        "id": "company_ninth_department",
                        "project_id": "T3B-COMPANY",
                        "departments": ["NINTH_DEPARTMENT"],
                        "source": {
                            "kind": "section_titles",
                            "paths": ["docs/store-assistant/en/topics/09_*.md"],
                            "languages": ["en"],
                        },
                        "gold": {"granularity": "section", "anchor_field": "structure_leaf"},
                        "gates": {"cross_department_leakage": 0},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    cases, suites = build_registered_suites(
        project_id="T3B-COMPANY",
        department="NINTH_DEPARTMENT",
        registry_path=registry,
    )

    assert cases
    assert {case["department"] for case in cases} == {"NINTH_DEPARTMENT"}
    assert suites[0]["gates"]["cross_department_leakage"] == 0


def test_store_registry_supports_store_operations_visibility() -> None:
    cases, suites = build_registered_suites(
        project_id="T2.0-STORE",
        department="STORE_OPERATIONS",
    )

    assert len(cases) == 368
    assert {case["department"] for case in cases} == {"STORE_OPERATIONS"}
    assert [suite["id"] for suite in suites] == ["store_canonical_questions"]


def test_store_out_of_scope_cases_feed_bilingual_refusal_metrics() -> None:
    cases = build_store_canonical_suite(
        STORE_DOCS / "en/topics/10_CANONICAL_QUESTION_INDEX.md",
        STORE_DOCS / "es/topics/10_INDICE_DE_PREGUNTAS_CANONICAS.md",
    )
    negatives = [case for case in cases if case["answerable"] is False]

    assert len(negatives) == 12
    assert {case["query_language"] for case in negatives} == {"en", "es"}
    assert {case["expected_refusal_reason"] for case in negatives} == {
        "INSUFFICIENT_EVIDENCE"
    }


def test_reviewed_references_join_without_changing_gold_cases(tmp_path) -> None:
    question = "Reviewed question"
    question_sha256 = hashlib.sha256(question.encode("utf-8")).hexdigest()
    path = tmp_path / "references.jsonl"
    path.write_text(
        json.dumps(
            {
                "case_id": "case-en",
                "query_language": "en",
                "target_evidence_language": "en",
                "question_sha256": question_sha256,
                "reference": "Reviewed answer",
                "reference_status": "reviewed",
                "dataset_version": "2026-09",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    cases = [
        {
            "id": "case-en",
            "query_language": "en",
            "target_evidence_language": "en",
            "question": question,
            "answerable": True,
            "gold_match": {"any_of": [{"field": "title", "equals": "Gold"}]},
        }
    ]
    merged = _apply_reviewed_references(
        cases, path, expected_dataset_version="2026-09"
    )
    assert merged[0]["reference"] == "Reviewed answer"
    assert merged[0]["gold_match"] == cases[0]["gold_match"]


def test_bilingual_ragas_requires_every_answerable_reference() -> None:
    cases = _load_evaluation_cases(EVALUATION / "bilingual_gold_suites.jsonl")
    cases[0] = {
        **cases[0],
        "reference": "Reviewed answer",
        "reference_status": "reviewed",
    }
    with pytest.raises(ValueError, match="references are incomplete"):
        _reviewed_bilingual_ragas_cases(cases)


def test_reference_template_covers_all_bilingual_answerable_cases() -> None:
    cases = _load_evaluation_cases(EVALUATION / "gold_suites.jsonl")
    references = build_reference_template(cases, "2026-09")
    assert len(references) == 60
    assert {row["query_language"] for row in references} == {"en", "es"}
    assert {
        (row["query_language"], row["target_evidence_language"])
        for row in references
    } >= {("en", "en"), ("es", "es"), ("en", "es"), ("es", "en")}
    assert all(row["reference_status"] == "pending_review" for row in references)
    assert all(
        row["question_sha256"]
        == hashlib.sha256(row["question_for_review"].encode("utf-8")).hexdigest()
        for row in references
    )


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


def test_score_uses_configured_cutoffs_and_project_boundary() -> None:
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

    assert summary["recall_at_1"] == 0
    assert summary["precision_at_1"] == 0
    assert summary["hit_rate_at_1"] == 0
    assert summary["mrr_at_1"] == 0
    assert summary["ndcg_at_1"] == 0
    assert summary["cross_project_leakage"] == 1


def test_precision_uses_fixed_k_when_rerank_list_is_short() -> None:
    settings = Settings(
        _env_file=None, environment="development", retrieval_top_k=25, rerank_top_n=8
    )
    summary = score(
        [
            {
                "answerable": True,
                "gold_chunk_ids": ["gold"],
                "retrieved_chunk_ids": ["gold"],
                "reranked_chunk_ids": ["gold"],
                "exposed_project_ids": ["T2.0"],
            }
        ],
        settings=settings,
        project_id="T2.0",
    )
    assert summary["precision_at_8"] == 1 / 8
    assert summary["ndcg_at_8"] == 1
    assert summary["answerable_cases"] == 1
    assert summary["gold_resolved_cases"] == 1
    assert summary["answer_evidence_cases"] == 1


def test_section_metrics_separate_candidate_recall_from_rerank_survival() -> None:
    settings = Settings(
        _env_file=None, environment="development", retrieval_top_k=25, rerank_top_n=16
    )
    summary = score(
        [
            {
                "answerable": True,
                "gold_chunk_ids": [f"gold-{index}" for index in range(30)],
                "gold_section_chunk_ids": [
                    [f"gold-{index}" for index in range(15)],
                    [f"gold-{index}" for index in range(15, 30)],
                ],
                "retrieved_chunk_ids": ["gold-1", "gold-16"],
                "reranked_chunk_ids": ["gold-1"],
                "exposed_project_ids": ["T2.0-STORE"],
            }
        ],
        settings=settings,
        project_id="T2.0-STORE",
    )

    assert summary["candidate_hit_rate_at_25"] == 1
    assert summary["section_hit_rate_at_16"] == 1
    assert summary["section_recall_at_16"] == 0.5
    assert summary["recall_at_25"] == 2 / 30
    assert summary["recall_at_25_gold_size_ceiling"] == 25 / 30


def test_retrieval_annotations_use_metric_population_denominators() -> None:
    settings = Settings(
        _env_file=None, environment="development", retrieval_top_k=25, rerank_top_n=8
    )
    rows = [
        {
            "answerable": True,
            "role": role,
            "gold_chunk_ids": ["gold"],
            "retrieved_chunk_ids": ["gold"],
            "reranked_chunk_ids": ["gold"],
            "exposed_project_ids": ["T2.0"],
        }
        for role in ("answer_evidence", "diagnostic")
    ]
    counts = retrieval_dashboard_sample_counts(
        score(rows, settings=settings, project_id="T2.0")
    )
    assert counts["recall_at_25.overall"] == 2
    assert counts["precision_at_8.overall"] == 1


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


def test_generation_metrics_count_uncited_claims_dropped() -> None:
    summary = score_generation(
        [
            {
                "answerable": True,
                "answered": True,
                "grounding_accepted": True,
                "cited_source_ids": ["page:1"],
                "valid_citation_count": 1,
                "uncited_claims_dropped": 2,
            },
            {
                "answerable": True,
                "answered": True,
                "grounding_accepted": True,
                "cited_source_ids": ["page:2"],
                "valid_citation_count": 1,
                "uncited_claims_dropped": 1,
            },
        ]
    )

    assert summary["uncited_claims_dropped"] == 3


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
    assert summary["language_gap"]["hit_rate_at_8"] == 1
    assert summary["language_gap_abs"]["hit_rate_at_8"] == 1
    dashboard = retrieval_dashboard_scores(summary)
    assert dashboard["ndcg_at_8.overall"] == 0.5
    assert dashboard["ndcg_at_8.en"] == 1
    assert dashboard["ndcg_at_8.es"] == 0
    assert dashboard["ndcg_at_8.language_gap"] == 1


def test_retrieval_signed_language_gap_preserves_direction() -> None:
    settings = Settings(_env_file=None, retrieval_top_k=25, rerank_top_n=8)
    rows = [
        {
            "query_language": language,
            "answerable": True,
            "gold_chunk_ids": ["gold"],
            "retrieved_chunk_ids": ["gold"] if language == "es" else [],
            "reranked_chunk_ids": ["gold"] if language == "es" else [],
            "exposed_project_ids": ["T2.0"],
        }
        for language in ("en", "es")
    ]
    summary = score(rows, settings=settings, project_id="T2.0")
    assert summary["language_gap"]["hit_rate_at_8"] == -1
    assert summary["language_gap_abs"]["hit_rate_at_8"] == 1


def test_reviewed_reference_rejects_question_or_dataset_drift(tmp_path) -> None:
    reference = {
        "case_id": "case-en",
        "query_language": "en",
        "target_evidence_language": "en",
        "question_sha256": "wrong",
        "reference": "Reviewed answer",
        "reference_status": "reviewed",
        "dataset_version": "v1",
    }
    path = tmp_path / "references.jsonl"
    path.write_text(json.dumps(reference) + "\n", encoding="utf-8")
    cases = [
        {
            "id": "case-en",
            "question": "Current question",
            "query_language": "en",
            "target_evidence_language": "en",
        }
    ]
    with pytest.raises(ValueError, match="question_sha256"):
        _apply_reviewed_references(cases, path, expected_dataset_version="v1")
    with pytest.raises(ValueError, match="dataset_version mismatch"):
        _apply_reviewed_references(cases, path, expected_dataset_version="v2")


def test_generation_lane_rejects_duplicate_stale_rows(tmp_path) -> None:
    output = tmp_path / "ragas.jsonl"
    row = {"id": "case-1"}
    output.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(RuntimeError, match="expected 1 rows, found 2"):
        asyncio.run(
            _run_generation_lane(
                [{"id": "case-1"}],
                settings=SimpleNamespace(),
                project_id="T2.0",
                output=output,
                recorded_candidates={},
            )
        )


def test_generation_lane_always_captures_local_pairwise_content(
    tmp_path, monkeypatch
) -> None:
    from app.workflow_evaluation import WorkflowEvaluationResult

    response = RagResponse(
        answer="Grounded answer",
        status="ANSWERED",
        confidence="HIGH",
        projectId="T2.0",
        sources=[],
        missingInformation=[],
        evidenceStatus="SUFFICIENT",
    )

    captured_requests = []
    captured_candidates = []

    class FakeWorkflow:
        def __init__(self, _settings, request, candidates):
            captured_requests.append(request)
            captured_candidates.append(candidates)

        async def run_for_evaluation(self):
            return WorkflowEvaluationResult(
                response=response,
                retrieved_contexts=("local evidence",),
                query_language="en",
                answer_style="direct",
                context_relevance=0.42,
                answer_relevance=0.73,
                pre_gate_draft_answer="Draft answer [SOURCE 1]",
                answer_relevance_scorer_question="resolved question",
                answer_relevance_scorer_answer="Draft answer",
            )

    monkeypatch.setattr(
        "evaluation.run_retrieval_eval._RecordedCandidateWorkflow", FakeWorkflow
    )
    settings = SimpleNamespace(
        chroma_collection="collection",
        supported_embedding_models=("model",),
        supported_schema_versions=("3",),
    )
    rows = asyncio.run(
        _run_generation_lane(
            [
                {
                    "id": "case-1",
                    "question": "Local question",
                    "answerable": True,
                    "query_language": "en",
                    "department": "STORE_OPERATIONS",
                }
            ],
            settings=settings,
            project_id="T2.0",
            output=tmp_path / "generation.jsonl",
            recorded_candidates={
                "case-1": [
                    Document(
                        page_content="recorded retrieval evidence",
                        metadata={"chunk_id": "chunk-1"},
                    )
                ]
            },
        )
    )

    assert rows[0]["user_input"] == "Local question"
    assert rows[0]["response"] == "Grounded answer"
    assert rows[0]["retrieved_contexts"] == ["local evidence"]
    assert rows[0]["answer_style"] == "direct"
    assert rows[0]["context_relevance"] == 0.42
    assert rows[0]["answer_relevance"] == 0.73
    assert rows[0]["pre_gate_draft_answer"] == "Draft answer [SOURCE 1]"
    assert rows[0]["pre_gate_answer_relevance"] == 0.73
    assert rows[0]["answer_relevance_pair"] == {
        "question": "resolved question",
        "answer": "Draft answer",
    }
    assert captured_requests[0].access_policy_ids == [
        "project:T2.0",
        "department:T2.0:STORE_OPERATIONS",
    ]
    assert captured_candidates[0][0].metadata["chunk_id"] == "chunk-1"


def test_generation_lane_types_a_silent_no_answer(tmp_path, monkeypatch) -> None:
    from app.workflow_evaluation import WorkflowEvaluationResult

    response = RagResponse(
        answer="Verified guidance was not found.",
        status="INSUFFICIENT_EVIDENCE",
        confidence="NONE",
        projectId="T2.0-STORE",
        sources=[],
        missingInformation=[],
        evidenceStatus="INSUFFICIENT",
    )

    class FakeWorkflow:
        def __init__(self, _settings, _request, _candidates):
            pass

        async def run_for_evaluation(self):
            return WorkflowEvaluationResult(
                response=response,
                retrieved_contexts=(),
                query_language="en",
            )

    monkeypatch.setattr(
        "evaluation.run_retrieval_eval._RecordedCandidateWorkflow", FakeWorkflow
    )
    settings = SimpleNamespace(
        chroma_collection="collection",
        supported_embedding_models=("model",),
        supported_schema_versions=("3",),
    )
    rows = asyncio.run(
        _run_generation_lane(
            [{
                "id": "silent-no-answer",
                "question": "Question without a verified answer",
                "answerable": True,
                "query_language": "en",
            }],
            settings=settings,
            project_id="T2.0-STORE",
            output=tmp_path / "generation.jsonl",
            recorded_candidates={"silent-no-answer": []},
        )
    )

    assert rows[0]["refusal_reason"] == "INSUFFICIENT_EVIDENCE"
    assert rows[0]["generated_outcome"] == "REFUSAL"
    assert rows[0]["generated_refusal_reason"] == "INSUFFICIENT_EVIDENCE"


def test_recorded_candidate_workflow_reuses_only_authorized_documents() -> None:
    workflow = object.__new__(_RecordedCandidateWorkflow)
    workflow._request = SimpleNamespace(
        project_id="T2.0-STORE",
        access_policy_ids=["project:T2.0-STORE"],
        question="How do I close the register?",
    )
    workflow._recorded_candidates = (
        Document(
            page_content="Closing guidance",
            metadata={
                "chunk_id": "close-1",
                "project_id": "T2.0-STORE",
                "access_policy_id": "project:T2.0-STORE",
            },
        ),
    )

    result = asyncio.run(
        workflow._retrieve(
            {
                "queries": ("How do I close the register?",),
                "resolved_question": "How do I close the register?",
            }
        )
    )

    assert [item.metadata["chunk_id"] for item in result["candidates"]] == [
        "close-1"
    ]
    assert result["fused_candidate_count"] == 1


def test_recorded_candidate_workflow_fails_closed_on_foreign_policy() -> None:
    workflow = object.__new__(_RecordedCandidateWorkflow)
    workflow._request = SimpleNamespace(
        project_id="T2.0-STORE",
        access_policy_ids=["project:T2.0-STORE"],
        question="Question",
    )
    workflow._recorded_candidates = (
        Document(
            page_content="Foreign evidence",
            metadata={
                "project_id": "T2.0",
                "access_policy_id": "project:T2.0",
            },
        ),
    )

    with pytest.raises(RuntimeError, match="outside the generation request"):
        asyncio.run(workflow._retrieve({"queries": ("Question",)}))


def test_recorded_candidate_ids_are_rehydrated_in_recorded_order() -> None:
    class Collection:
        def get(self, **_kwargs):
            return {
                "ids": ["physical-2", "physical-1"],
                "documents": ["second", "first"],
                "metadatas": [
                    {"canonical_chunk_id": "chunk-2"},
                    {"canonical_chunk_id": "chunk-1"},
                ],
            }

    candidates = _rehydrate_recorded_candidates(
        [{"id": "case-1", "retrieved_chunk_ids": ["chunk-1", "chunk-2"]}],
        Collection(),
    )

    assert [item.page_content for item in candidates["case-1"]] == [
        "first",
        "second",
    ]
    assert candidates["case-1"][0].metadata["retrieval_fused_score"] == 1


def test_generation_candidate_rows_reuse_existing_retrieval_row(tmp_path) -> None:
    retrieval_row = {"id": "case-1", "retrieved_chunk_ids": ["chunk-1"]}

    rows = asyncio.run(
        _generation_candidate_rows(
            [{"id": "case-1"}],
            retrieval_rows=[retrieval_row],
            manifest={},
            retriever=None,
            sparse=None,
            fusion=None,
            reranker=None,
            settings=None,
            output=tmp_path / "candidates.jsonl",
            lexical_enabled=True,
        )
    )

    assert rows == [retrieval_row]
    assert not (tmp_path / "candidates.jsonl").exists()


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


def test_generation_metrics_include_language_split_and_signed_gap() -> None:
    rows = [
        {
            "query_language": language,
            "answerable": True,
            "answered": accepted,
            "grounding_accepted": accepted,
            "cited_source_ids": [],
        }
        for language, accepted in (("en", False), ("es", True))
    ]
    summary = score_generation(rows)
    dashboard = generation_dashboard_scores(summary)
    assert dashboard["grounding_acceptance_rate.en"] == 0
    assert dashboard["grounding_acceptance_rate.es"] == 1
    assert dashboard["grounding_acceptance_rate.language_gap"] == -1
    assert dashboard["grounding_acceptance_rate.language_gap_abs"] == 1
    counts = generation_dashboard_sample_counts(summary)
    assert counts["grounding_acceptance_rate.overall"] == 2
    assert counts["citation_precision.overall"] == 0


def test_refusal_quality_metrics_are_reported_per_language() -> None:
    rows = [
        {
            "query_language": "en",
            "answerable": False,
            "answered": False,
            "refusal_reason": "SOURCE_SCOPE_VIOLATION",
            "cited_source_ids": [],
        },
        {
            "query_language": "es",
            "answerable": False,
            "answered": True,
            "cited_source_ids": [],
        },
    ]

    summary = score_generation(rows)
    dashboard = generation_dashboard_scores(summary)

    assert dashboard["refusal_precision.en"] == 1
    assert dashboard["refusal_precision.es"] == 0
    assert dashboard["out_of_scope_answer_rate.en"] == 0
    assert dashboard["out_of_scope_answer_rate.es"] == 1


def test_generation_score_reports_canonical_fallback_impact() -> None:
    rows = [
        {
            "query_language": "en",
            "answerable": False,
            "answered": True,
            "cited_source_ids": ["page-1"],
            "canonical_fallback_used": True,
            "canonical_fallback_reason": "EMPTY_MODEL_RESPONSE",
        },
        {
            "query_language": "en",
            "answerable": False,
            "answered": False,
            "refusal_reason": "INSUFFICIENT_EVIDENCE",
            "cited_source_ids": [],
            "canonical_fallback_used": False,
        },
    ]

    summary = score_generation(rows)

    assert summary["canonical_fallback_cases"] == 1
    assert summary["canonical_fallback_reasons"] == {"EMPTY_MODEL_RESPONSE": 1}
    assert summary["out_of_scope_answer_rate"] == 0.5
    assert summary["legacy_out_of_scope_answer_rate"] == 0.5
    assert summary["out_of_scope_answer_rate_excluding_canonical_fallback"] == 0


def test_real_prose_refusals_are_scored_from_typed_outcomes() -> None:
    rows = [
        {
            "id": "store-en-184",
            "query_language": "en",
            "answerable": False,
            "answered": True,
            "refusal_reason": "SOURCE_SCOPE_VIOLATION",
            "answer": (
                "I cannot help with Windows, Android, or macOS because this assistant "
                "covers only visible POS and BOT operation and troubleshooting for Linux "
                "stores. I can instead help with access, sales, payments, printing, "
                "merchandise, inventory, orders, cash, and closure."
            ),
        },
        {
            "id": "store-es-182",
            "query_language": "es",
            "answerable": False,
            "answered": True,
            "refusal_reason": "UNVERIFIED_EVIDENCE",
            "answer": (
                "No puedo proporcionarte instrucciones para instalar o desplegar Tiendas "
                "2.0 Linux, ya que el asistente est\u00e1 dise\u00f1ado exclusivamente para ayudar "
                "con la operaci\u00f3n visible de puntos de venta (POS) y botellas (BOT), as\u00ed "
                "como para solucionar problemas en tiendas Linux."
            ),
        },
        {
            "id": "store-es-184",
            "query_language": "es",
            "answerable": False,
            "answered": True,
            "refusal_reason": "SOURCE_SCOPE_VIOLATION",
            "answer": (
                "No puedo ayudarte con Windows, Android o macOS porque este asistente solo "
                "cubre la operaci\u00f3n y soluci\u00f3n de problemas visibles de POS y BOT en "
                "tiendas Linux. Si necesitas asistencia, por favor consulta temas "
                "relacionados con acceso, ventas, pagos, impresi\u00f3n, mercanc\u00eda, inventario, "
                "pedidos, efectivo o cierres de Tiendas 2.0 Linux."
            ),
        },
    ]

    summary = score_generation(rows)

    assert summary["legacy_out_of_scope_answer_rate"] == 1
    assert summary["out_of_scope_answer_rate"] == 0
    assert summary["refusal_precision"] == 1
    assert summary["by_query_language"]["en"]["out_of_scope_answer_rate"] == 0
    assert summary["by_query_language"]["es"]["out_of_scope_answer_rate"] == 0


def test_default_suite_has_bilingual_fast_lane_and_negative_reasons() -> None:
    cases = _load_evaluation_cases(EVALUATION / "gold_suites.jsonl")
    fast_lane = [case for case in cases if case.get("evaluation_lane") != "generation"]
    negatives = [case for case in cases if case.get("answerable") is False]
    sample = _stratified_sample(cases, 30)

    assert len(fast_lane) == 378
    assert len(negatives) == 60
    assert {
        language: sum(
            case.get("query_language") == language for case in negatives
        )
        for language in ("en", "es")
    } == {"en": 30, "es": 30}
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
    negatives = [case for case in sample if case.get("answerable") is False]
    negative_counts = {
        language: sum(case.get("query_language") == language for case in negatives)
        for language in ("en", "es")
    }
    assert negative_counts["en"] == negative_counts["es"]
    assert negative_counts["es"] >= 3
    assert {case.get("query_language") for case in sample} >= {"en", "es"}


def test_store_generation_sample_never_injects_developer_paraphrases() -> None:
    cases = _load_evaluation_cases(EVALUATION / "store_gold_suites.jsonl")
    sample = _generation_sample(cases, 30, project_id="T2.0-STORE")

    assert len(sample) == 30
    assert {case["project_id"] for case in sample} == {"T2.0-STORE"}
    assert not any(case.get("paraphrase_group") for case in sample)
    assert {case.get("query_language") for case in sample} == {"en", "es"}
    assert {case.get("answerable") for case in sample} == {True, False}


def test_store_generation_sample_covers_every_routed_section_in_both_languages() -> None:
    cases, _ = build_registered_suites(
        project_id="T2.0-STORE",
        department="STORE_OPERATIONS",
    )
    sample = _generation_sample(cases, 220, project_id="T2.0-STORE")

    expected_pairs = {
        (case["query_language"], section_id)
        for case in cases
        if case.get("answerable") is True
        for section_id in case.get("gold_section_ids", [])
    }
    sampled_pairs = {
        (case["query_language"], section_id)
        for case in sample
        if case.get("answerable") is True
        for section_id in case.get("gold_section_ids", [])
    }

    assert len(sample) == 220
    assert sum(case.get("query_language") == "en" for case in sample) == 110
    assert sum(case.get("query_language") == "es" for case in sample) == 110
    assert sampled_pairs == expected_pairs
    assert len(sampled_pairs) == 260
    assert sum(case.get("answerable") is False for case in sample) == 12
