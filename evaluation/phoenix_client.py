"""Content-safe Phoenix annotation publishing shared by evaluation lanes."""

from __future__ import annotations

import json
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def publish_scores_to_phoenix(
    url: str,
    span_id: str | None,
    scores: dict[str, float],
    sample_count: int,
    *,
    section: str = "answer_generation",
    metadata: dict[str, str | int | float] | None = None,
    annotator_kind: str = "LLM",
    sample_counts: dict[str, int] | None = None,
) -> None:
    """Attach aggregate scores and safe metadata to an existing Phoenix span."""

    if not url or not span_id:
        return
    annotations = []
    for name, value in scores.items():
        metric_sample_count = (
            sample_counts.get(name, sample_count) if sample_counts else sample_count
        )
        annotations.append(
            {
                "name": f"{section}.{name}",
                "annotator_kind": annotator_kind,
                "span_id": span_id,
                "identifier": f"{section}.{name}",
                "result": {"score": value},
                "metadata": {
                    "evaluator": (
                        "ragas" if annotator_kind == "LLM" else "deterministic"
                    ),
                    "sample_count": metric_sample_count,
                    "quality_section": section,
                    **(metadata or {}),
                },
            }
        )
    body = json.dumps({"data": annotations}).encode("utf-8")
    request = Request(
        f"{url.rstrip('/')}/v1/span_annotations?sync=true",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    deadline = time.monotonic() + 15
    while True:
        try:
            with urlopen(request, timeout=5) as response:
                if response.status != 200:
                    raise RuntimeError(f"Phoenix returned HTTP {response.status}")
            return
        except HTTPError as exc:
            if exc.code != 404 or time.monotonic() >= deadline:
                raise
            time.sleep(1)
