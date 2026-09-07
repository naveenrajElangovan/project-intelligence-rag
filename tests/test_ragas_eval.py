import json
import sys

import pytest

import pandas as pd
from prometheus_client import generate_latest

from evaluation.run_ragas_eval import (
    aggregate_scores,
    build_answer_metrics,
    load_samples,
    validate_judge_model,
    validate_bilingual_samples,
)
from evaluation.phoenix_client import publish_scores_to_phoenix


def test_ragas_dataset_requires_content_and_reference(tmp_path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        json.dumps(
            {
                "user_input": "question",
                "response": "answer",
                "retrieved_contexts": ["evidence"],
                "reference": "expected answer",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    assert load_samples(dataset)[0]["reference"] == "expected answer"


def test_ragas_dataset_rejects_missing_reference(tmp_path) -> None:
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text('{"user_input":"q","response":"a","retrieved_contexts":[]}\n')
    with pytest.raises(ValueError, match="reference"):
        load_samples(dataset)


def test_phoenix_annotations_contain_scores_but_no_rag_content(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("evaluation.phoenix_client.urlopen", fake_urlopen)
    publish_scores_to_phoenix("http://phoenix:6006", "0123456789abcdef", {"faithfulness": 0.9}, 4)

    assert captured["url"] == "http://phoenix:6006/v1/span_annotations?sync=true"
    annotation = captured["body"]["data"][0]
    assert annotation["span_id"] == "0123456789abcdef"
    assert annotation["result"] == {"score": 0.9}
    assert "user_input" not in json.dumps(captured["body"])
    assert annotation["name"] == "answer_generation.faithfulness"


def test_bilingual_samples_require_review_and_all_directions() -> None:
    base = {
        "user_input": "q",
        "response": "a",
        "retrieved_contexts": ["c"],
        "reference": "r",
        "reference_status": "reviewed",
    }
    samples = [
        {
            **base,
            "case_id": f"case-{query}-{evidence}",
            "query_language": query,
            "target_evidence_language": evidence,
        }
        for query, evidence in (("en", "en"), ("es", "es"), ("en", "es"), ("es", "en"))
    ]
    validate_bilingual_samples(samples)
    samples[0]["reference_status"] = "pending_review"
    with pytest.raises(ValueError, match="human-reviewed"):
        validate_bilingual_samples(samples)


def test_ragas_scores_include_overall_languages_and_gap() -> None:
    frame = pd.DataFrame(
        {
            "faithfulness": [1.0, 0.5],
            "answer_relevancy": [0.8, 0.6],
            "answer_correctness": [0.9, 0.7],
        }
    )
    samples = [{"query_language": "en"}, {"query_language": "es"}]
    scores = aggregate_scores(frame, samples)
    assert scores["faithfulness.overall"] == 0.75
    assert scores["faithfulness.en"] == 1.0
    assert scores["faithfulness.es"] == 0.5
    assert scores["faithfulness.language_gap"] == 0.5
    assert scores["faithfulness.language_gap_abs"] == 0.5


def test_ragas_signed_language_gap_preserves_direction() -> None:
    frame = pd.DataFrame(
        {
            "faithfulness": [0.25, 0.75],
            "answer_relevancy": [0.25, 0.75],
            "answer_correctness": [0.25, 0.75],
        }
    )
    scores = aggregate_scores(
        frame, [{"query_language": "en"}, {"query_language": "es"}]
    )
    assert scores["faithfulness.language_gap"] == -0.5
    assert scores["faithfulness.language_gap_abs"] == 0.5


def test_floating_judge_tag_requires_explicit_opt_out() -> None:
    with pytest.raises(ValueError, match="must be pinned"):
        validate_judge_model("qwen3.5:latest")
    assert (
        validate_judge_model("qwen3.5:latest", allow_floating=True)
        == "qwen3.5:latest"
    )


def test_quality_scores_are_not_prometheus_metrics() -> None:
    exposition = generate_latest().decode("utf-8")
    assert "ragas_faithfulness" not in exposition
    assert "pi_rag_precision_at_8" not in exposition
    assert "pi_rag_answer_correctness" not in exposition


def test_requested_answer_metrics_are_the_default_ragas_set() -> None:
    assert [metric.name for metric in build_answer_metrics()] == [
        "faithfulness",
        "answer_relevancy",
        "answer_correctness",
    ]
