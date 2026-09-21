"""Measure exact end-to-end answer reproducibility without exporting content."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
import uuid

import httpx

from app.config import Settings
from app.chroma_collections import configured_collection_name


def _fingerprint(payload: dict[str, object]) -> str:
    stable = {
        "answer": payload.get("answer"),
        "confidence": payload.get("confidence"),
        "status": payload.get("status"),
        "refusalReason": payload.get("refusalReason"),
        "sources": [
            {key: source.get(key) for key in ("chunkId", "sourceId", "title", "url", "sourceType")}
            for source in (payload.get("sources") or [])
            if isinstance(source, dict)
        ],
    }
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument(
        "--collection-name",
        default=None,
        help="Override the configured primary serving collection.",
    )
    parser.add_argument("--show-output", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--batch-id",
        default="",
        help="Stable label for correlating this batch with content-free server telemetry.",
    )
    arguments = parser.parse_args()
    if arguments.runs < 2:
        raise SystemExit("--runs must be at least 2")

    settings = Settings()
    collection_name = configured_collection_name(
        arguments.collection_name, settings.chroma_collection
    )
    headers: dict[str, str] = {}
    if settings.internal_api_key:
        headers["Authorization"] = f"Bearer {settings.internal_api_key}"
    fingerprints: list[str] = []
    durations: list[float] = []
    batch_id = arguments.batch_id or uuid.uuid4().hex[:12]
    with httpx.Client(timeout=180) as client:
        for index in range(arguments.runs):
            began = time.perf_counter()
            request_id = f"reproducibility-{batch_id}-{index + 1}"
            response = client.post(
                arguments.base_url.rstrip("/") + "/v1/answer",
                headers={**headers, "X-Request-ID": request_id},
                json={
                    "projectId": arguments.project_id,
                    "collectionName": collection_name,
                    "textField": "chunk_text",
                    "embeddingField": "embedding_text",
                    "embeddingModel": "multilingual-e5-large",
                    "schemaVersion": "3",
                    "question": arguments.question,
                    "accessPolicyIds": [f"project:{arguments.project_id}"],
                    "modelProfile": "budget",
                },
            )
            duration = time.perf_counter() - began
            durations.append(duration)
            response.raise_for_status()
            payload = response.json()
            fingerprint = _fingerprint(payload)
            fingerprints.append(fingerprint)
            if arguments.show_output:
                print(
                    json.dumps(
                        {
                            "run": index + 1,
                            "request_id": request_id,
                            "duration_seconds": duration,
                            "fingerprint": fingerprint,
                            "answer": payload.get("answer"),
                            "confidence": payload.get("confidence"),
                            "status": payload.get("status"),
                            "source_count": len(payload.get("sources") or []),
                            "source_titles": [
                                source.get("title")
                                for source in (payload.get("sources") or [])
                                if isinstance(source, dict)
                            ],
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )

    canonical = fingerprints[0]
    matching = sum(value == canonical for value in fingerprints)
    result = {
        "batch_id": batch_id,
        "logical_collection": collection_name,
        "runs": arguments.runs,
        "matching_runs": matching,
        "consistency_rate": matching / arguments.runs,
        "unique_outputs": len(set(fingerprints)),
        "fingerprints": fingerprints,
        "duration_seconds": {
            "min": min(durations),
            "max": max(durations),
            "mean": sum(durations) / len(durations),
        },
    }
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if arguments.output is not None:
        arguments.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    raise SystemExit(0 if matching == arguments.runs else 1)


if __name__ == "__main__":
    main()
