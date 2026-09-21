"""Measure Ollama decode throughput across a repeatable prompt sample."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from statistics import median

import httpx


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round((len(ordered) - 1) * fraction))]


def prompts(path: Path) -> list[str]:
    values: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        value = json.loads(line)
        question = str(value.get("question") or value.get("user_input") or "").strip()
        if question:
            values.append(question)
    if not values:
        raise ValueError("the prompt sample contains no questions")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:11434")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=300.0)
    args = parser.parse_args()

    rows: list[dict[str, float | int]] = []
    with httpx.Client(timeout=args.timeout) as client:
        for question in prompts(args.input)[: max(1, args.limit)]:
            response = client.post(
                f"{args.base_url.rstrip('/')}/api/chat",
                json={
                    "model": args.model,
                    "stream": False,
                    "think": False,
                    "options": {"temperature": 0, "seed": 0, "num_predict": 128},
                    "messages": [
                        {"role": "system", "content": "Answer factually and concisely."},
                        {"role": "user", "content": question},
                    ],
                },
            )
            response.raise_for_status()
            result = response.json()
            count = int(result.get("eval_count") or 0)
            duration_ns = int(result.get("eval_duration") or 0)
            if count <= 0 or duration_ns <= 0:
                raise ValueError("Ollama response omitted eval_count or eval_duration")
            rows.append(
                {
                    "output_tokens": count,
                    "decode_seconds": duration_ns / 1_000_000_000,
                    "tokens_per_second": count / (duration_ns / 1_000_000_000),
                }
            )
    rates = [float(row["tokens_per_second"]) for row in rows]
    print(
        json.dumps(
            {
                "model": args.model,
                "sample_count": len(rows),
                "tokens_per_second_p50": round(median(rates), 3),
                "tokens_per_second_p95": round(percentile(rates, 0.95), 3),
                "total_output_tokens": sum(int(row["output_tokens"]) for row in rows),
                "runs": rows,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
