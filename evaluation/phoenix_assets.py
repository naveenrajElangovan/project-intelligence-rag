"""Versioned Phoenix dataset, prompt, experiment, and evaluator assets."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Iterable
from urllib.error import HTTPError

from evaluation.phoenix_client import PhoenixClient


DATASET_SCHEMA_VERSION = "1"
EVALUATOR_SUITE_VERSION = "2026-09-10.1"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def read_jsonl(paths: Iterable[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number} must be an object")
            rows.append(value)
    return rows


def standardize_examples(
    rows: Iterable[dict[str, Any]], *, boundary: str, dataset_version: str
) -> list[dict[str, Any]]:
    """Convert gold rows and reject cross-boundary or duplicate content."""

    expected_project = boundary.removeprefix("project:")
    examples: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in rows:
        case_id = str(row.get("case_id") or row.get("id") or "").strip()
        project_id = str(row.get("project_id") or "").strip()
        if not case_id or not project_id or not row.get("question"):
            raise ValueError("every gold row requires id, project_id, and question")
        if project_id != expected_project:
            raise ValueError(f"case {case_id} belongs to project:{project_id}, not {boundary}")
        if case_id in seen:
            raise ValueError(f"duplicate case_id: {case_id}")
        seen.add(case_id)
        language = str(row.get("query_language") or row.get("language") or "unknown")
        persona = str(row.get("persona") or row.get("role") or "unspecified")
        reference = row.get("reviewed_reference", row.get("reference", ""))
        expected_sources = row.get("expected_sources", row.get("gold_match", {}))
        normalized = {
            "case_id": case_id,
            "project_id": project_id,
            "policy_boundary": boundary,
            "language": language,
            "persona": persona,
            "question": str(row["question"]),
            "reviewed_reference": reference,
            "expected_sources": expected_sources,
            "answerability": bool(row.get("answerable", True)),
            "tags": sorted({str(row.get("suite") or "gold"), language, persona, *(str(tag) for tag in row.get("tags", []))}),
            "dataset_version": dataset_version,
            "schema_version": DATASET_SCHEMA_VERSION,
        }
        examples.append(
            {
                "example_id": case_id,
                "inputs": {"question": normalized["question"], "language": language, "persona": persona, "project_id": project_id},
                "outputs": {"reference": reference, "expected_sources": expected_sources, "answerable": normalized["answerability"]},
                "metadata": {**normalized, "content_hash": canonical_hash(normalized)},
                "splits": normalized["tags"],
            }
        )
    return examples


def git_sha(root: Path) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()


def prompt_payload(
    *, name: str, template: str, owner: str, sha: str, tag: str, model_name: str,
    model_provider: str = "OLLAMA",
) -> dict[str, Any]:
    """Build one Git-controlled Phoenix prompt version."""

    return {
        "prompt": {
            "name": name,
            "description": "Git-controlled Project Intelligence prompt",
            "metadata": {"git_sha": sha, "schema_version": "1", "owner": owner, "release_tag": tag, "content_hash": canonical_hash(template)},
        },
        "version": {
            "model_provider": model_provider,
            "model_name": model_name,
            "template": {"type": "chat", "messages": [{"role": "system", "content": template}]},
            "template_type": "CHAT",
            "template_format": "MUSTACHE",
            "invocation_parameters": {
                "type": model_provider.casefold(),
                model_provider.casefold(): {"temperature": 0},
            },
        },
    }


def publish_experiment(
    client: PhoenixClient, *, dataset_id: str, name: str,
    candidate: dict[str, Any], rows: Iterable[dict[str, Any]],
) -> str:
    """Publish per-example outputs and evaluations, never aggregates only."""

    created = client.create_experiment(dataset_id, {"name": name, "metadata": candidate, "repetitions": 1})
    experiment_id = str(created.get("data", created)["id"])
    for row in rows:
        now = datetime.now(timezone.utc).isoformat()
        run_payload = {
            "dataset_example_id": row["dataset_example_id"],
            "output": row.get("output", {}),
            "repetition_number": 1,
            "start_time": row.get("start_time") or now,
            "end_time": row.get("end_time") or now,
        }
        for optional in ("trace_id", "error"):
            if row.get(optional) is not None:
                run_payload[optional] = row[optional]
        run = client.create_experiment_run(experiment_id, run_payload)
        run_id = str(run.get("data", run)["id"])
        for evaluation in row.get("evaluations", []):
            result = {key: evaluation[key] for key in ("label", "score", "explanation") if key in evaluation}
            client.upsert_experiment_evaluation(
                {
                    "experiment_run_id": run_id,
                    "name": evaluation["name"],
                    "annotator_kind": evaluation.get("annotator_kind", "CODE"),
                    "start_time": evaluation.get("start_time") or now,
                    "end_time": evaluation.get("end_time") or now,
                    "result": result,
                    "metadata": {"evaluator_suite_version": EVALUATOR_SUITE_VERSION, **evaluation.get("metadata", {})},
                    **({"trace_id": row["trace_id"]} if row.get("trace_id") else {}),
                }
            )
    return experiment_id


def ensure_immutable_dataset(
    client: PhoenixClient, *, name: str, description: str,
    metadata: dict[str, Any], examples: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create once; a byte-equivalent retry succeeds without a new version."""

    try:
        return client.upload_dataset(
            name=name, description=description, metadata=metadata,
            examples=examples, action="create",
        )
    except HTTPError as failure:
        if failure.code != 409:
            raise
    datasets = client.list_datasets(name=name).get("data", [])
    match = next((item for item in datasets if item.get("name") == name), None)
    if not match:
        raise RuntimeError(f"Phoenix reported duplicate dataset {name}, but it cannot be read")
    remote = client.get_dataset_examples(str(match["id"])).get("data", {}).get("examples", [])
    remote_identity = sorted(
        (str((item.get("metadata") or {}).get("case_id") or ""), str((item.get("metadata") or {}).get("content_hash") or ""))
        for item in remote
    )
    expected_identity = sorted(
        (str(item["metadata"]["case_id"]), str(item["metadata"]["content_hash"]))
        for item in examples
    )
    if remote_identity != expected_identity:
        raise RuntimeError(
            f"immutable dataset {name} already exists with different content"
        )
    return {"data": {"dataset_id": match["id"], "idempotent": True}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Synchronize an immutable Phoenix dataset")
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument("--boundary", required=True, help="For example project:T2.0")
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--phoenix-url", default=os.getenv("PI_RAG_PHOENIX_URL", "http://127.0.0.1:6006"))
    parser.add_argument("--api-key", default=os.getenv("PI_RAG_PHOENIX_API_KEY", ""))
    args = parser.parse_args()
    examples = standardize_examples(read_jsonl(args.paths), boundary=args.boundary, dataset_version=args.dataset_version)
    name = f"rag-gold-{args.boundary.replace(':', '-')}-v{args.dataset_version}"
    ensure_immutable_dataset(
        PhoenixClient(args.phoenix_url, args.api_key),
        name=name,
        description="Reviewed, immutable Project Intelligence gold suite",
        metadata={"policy_boundary": args.boundary, "dataset_version": args.dataset_version, "schema_version": DATASET_SCHEMA_VERSION, "content_hash": canonical_hash(examples), "imported_at": datetime.now(timezone.utc).isoformat()},
        examples=examples,
    )


if __name__ == "__main__":
    main()
