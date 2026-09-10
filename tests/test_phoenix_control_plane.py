from dataclasses import dataclass, field
import re

import pytest

from app.config import Settings
from app.openinference_tracing import _BoundarySpanProcessor
from app.quality_tracing import redact_trace_text
from evaluation.phoenix_client import PhoenixClient
from evaluation.phoenix_assets import (
    canonical_hash,
    prompt_payload,
    publish_experiment,
    standardize_examples,
)
from evaluation.deterministic_evaluators import evaluate_case
from evaluation.sync_prompts import prompt_templates


def test_trace_content_policy_defaults_to_metadata_only() -> None:
    settings = Settings(_env_file=None, environment="development")
    assert settings.openinference_content_mode == "metadata_only"
    assert settings.openinference_success_sample_rate == 0.10


def test_boundary_processor_supports_pre_end_sdk_hook() -> None:
    processor = _BoundarySpanProcessor()
    processor._on_ending(object())


def test_trace_text_redacts_credentials() -> None:
    value = redact_trace_text(
        "authorization: Bearer abc.def token=secret password=hunter2 useful content"
    )
    assert "abc.def" not in value
    assert "secret" not in value
    assert "hunter2" not in value
    assert "useful content" in value


def test_dataset_rows_are_stable_and_project_isolated() -> None:
    row = {
        "id": "case-1",
        "project_id": "T2.0",
        "question": "What happened?",
        "query_language": "en",
        "role": "developer",
        "answerable": True,
        "gold_match": {"field": "title", "contains": "Event"},
    }
    first = standardize_examples([row], boundary="project:T2.0", dataset_version="7")
    second = standardize_examples([row], boundary="project:T2.0", dataset_version="7")
    assert first == second
    assert first[0]["metadata"]["content_hash"] == canonical_hash(
        {key: value for key, value in first[0]["metadata"].items() if key != "content_hash"}
    )
    with pytest.raises(ValueError, match="not project:T2.0"):
        standardize_examples(
            [{**row, "project_id": "OTHER"}],
            boundary="project:T2.0",
            dataset_version="7",
        )


def test_prompt_version_contains_release_identity() -> None:
    payload = prompt_payload(
        name="answer-generation",
        template="Use only {{evidence}}.",
        owner="ai-platform",
        sha="deadbeef",
        tag="candidate",
        model_name="qwen3.5",
    )
    assert payload["prompt"]["metadata"]["git_sha"] == "deadbeef"
    assert payload["prompt"]["metadata"]["release_tag"] == "candidate"
    assert payload["version"]["template"]["messages"][0]["content"] == "Use only {{evidence}}."


@dataclass
class FakePhoenix:
    calls: list[tuple[str, object]] = field(default_factory=list)

    def create_experiment(self, dataset_id, payload):
        self.calls.append(("experiment", (dataset_id, payload)))
        return {"data": {"id": "experiment-1"}}

    def create_experiment_run(self, experiment_id, payload):
        self.calls.append(("run", (experiment_id, payload)))
        return {"data": {"id": "run-1"}}

    def upsert_experiment_evaluation(self, payload):
        self.calls.append(("evaluation", payload))
        return {}


def test_experiments_publish_row_level_evaluations() -> None:
    client = FakePhoenix()
    experiment_id = publish_experiment(
        client,  # type: ignore[arg-type]
        dataset_id="dataset-1",
        name="candidate-a",
        candidate={"prompt_version": "a", "model": "m"},
        rows=[
            {
                "dataset_example_id": "example-1",
                "output": {"answer": "ok"},
                "trace_id": "trace-1",
                "evaluations": [
                    {"name": "citation_validity", "score": 1.0},
                    {"name": "groundedness", "score": 0.9, "annotator_kind": "LLM"},
                ],
            }
        ],
    )
    assert experiment_id == "experiment-1"
    evaluations = [payload for kind, payload in client.calls if kind == "evaluation"]
    assert [item["name"] for item in evaluations] == ["citation_validity", "groundedness"]
    assert all(item["experiment_run_id"] == "run-1" for item in evaluations)
    assert all("evaluator_suite_version" in item["metadata"] for item in evaluations)


def test_deterministic_suite_detects_cross_project_candidate() -> None:
    results = {
        result.name: result
        for result in evaluate_case(
            {
                "answer": "The event is active [SOURCE 1].",
                "status": "ANSWERED",
                "sources": [{"reference": "event-1"}],
                "expected_sources": ["event-1"],
                "project_id": "A",
                "candidate_metadata": [{"project_id": "B"}],
                "language": "en",
                "answerable": True,
                "latency_ms": 200,
                "latency_budget_ms": 1000,
            }
        )
    }
    assert results["authorization_leakage"].label == "FAIL"
    assert results["citation_validity"].label == "PASS"
    assert results["source_coverage"].score == 1


def test_git_prompt_extractor_finds_named_templates() -> None:
    prompts = list(prompt_templates(__import__("pathlib").Path("app/llm.py")))
    assert prompts
    assert len({name for name, _ in prompts}) == len(prompts)
    assert all(re.fullmatch(r"[a-z0-9](?:[_a-z0-9-]*[a-z0-9])?", name) for name, _ in prompts)
    assert all(template.strip() for _, template in prompts)


def test_dataset_upload_uses_phoenix_parallel_array_contract() -> None:
    captured = {}

    class Client(PhoenixClient):
        def _request(self, method, path, payload=None):
            captured.update(method=method, path=path, payload=payload)
            return {"data": {"dataset_id": "d1"}}

    Client("http://phoenix").upload_dataset(
        name="gold-v1",
        description="reviewed",
        metadata={"policy_boundary": "project:A"},
        examples=[
            {
                "example_id": "case-1",
                "inputs": {"question": "q"},
                "outputs": {"reference": "a"},
                "metadata": {"content_hash": "hash"},
                "splits": ["en"],
            }
        ],
    )
    assert captured["path"] == "/v1/datasets/upload"
    assert captured["payload"]["inputs"] == [{"question": "q"}]
    assert "example_ids" not in captured["payload"]
    assert captured["payload"]["metadata"][0]["dataset_metadata"]["policy_boundary"] == "project:A"
