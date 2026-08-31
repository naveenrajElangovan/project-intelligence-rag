"""Measure content-free timing for the verified NDJSON answer stream."""

from __future__ import annotations

import argparse
import json
import time
import statistics

import httpx

from app.config import Settings


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def main() -> None:
    """Send authorized questions and report token latency without answer content."""

    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8003")
    parser.add_argument("--runs", type=int, default=3)
    arguments = parser.parse_args()
    settings = Settings()
    headers = {"Accept": "application/x-ndjson"}
    if settings.internal_api_key:
        headers["Authorization"] = f"Bearer {settings.internal_api_key}"
    payload = {
        "projectId": arguments.project_id,
        "collectionName": settings.chroma_collection,
        "textField": "chunk_text",
        "embeddingField": "embedding_text",
        "embeddingModel": "multilingual-e5-large",
        "schemaVersion": "3",
        "question": arguments.question,
        "accessPolicyIds": [f"project:{arguments.project_id}"],
        "modelProfile": "budget",
    }
    runs: list[dict[str, object]] = []
    with httpx.Client(timeout=180) as client:
        for _ in range(max(1, arguments.runs)):
            began = time.perf_counter()
            first_event_seconds: float | None = None
            first_answer_seconds: float | None = None
            delta_times: list[float] = []
            answer_characters = 0
            confidence = "NONE"
            event_count = 0
            with client.stream(
                "POST",
                f"{arguments.base_url.rstrip('/')}/v1/answer/stream",
                headers=headers,
                json=payload,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    event_count += 1
                    elapsed = time.perf_counter() - began
                    first_event_seconds = first_event_seconds or elapsed
                    event = json.loads(line)
                    if event.get("type") == "answer_delta":
                        first_answer_seconds = first_answer_seconds or elapsed
                        delta_times.append(elapsed)
                        answer_characters += len(str(event.get("delta") or ""))
                    if event.get("type") == "complete":
                        result = event.get("response") or {}
                        confidence = str(result.get("confidence") or "NONE")
            total_seconds = time.perf_counter() - began
            gaps = [
                later - earlier
                for earlier, later in zip(delta_times, delta_times[1:])
            ]
            runs.append(
                {
                    "first_event_ms": (first_event_seconds or total_seconds) * 1000,
                    "first_answer_ms": (first_answer_seconds or total_seconds) * 1000,
                    "total_ms": total_seconds * 1000,
                    "event_count": event_count,
                    "answer_characters": answer_characters,
                    "confidence": confidence,
                    "inter_delta_gaps_ms": [gap * 1000 for gap in gaps],
                }
            )
    first_answers = [float(run["first_answer_ms"]) for run in runs]
    all_gaps = [
        float(gap)
        for run in runs
        for gap in run["inter_delta_gaps_ms"]
    ]
    print(
        json.dumps(
            {
                "runs": len(runs),
                "time_to_first_token_p95_ms": round(_percentile(first_answers, 0.95), 2),
                "inter_delta_gap_p50_ms": round(statistics.median(all_gaps), 2)
                if all_gaps
                else 0,
                "inter_delta_gap_p95_ms": round(_percentile(all_gaps, 0.95), 2),
                "burst_gap_fraction_under_5ms": round(
                    sum(gap < 5 for gap in all_gaps) / len(all_gaps), 3
                )
                if all_gaps
                else 0,
                "details": runs,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    main()
