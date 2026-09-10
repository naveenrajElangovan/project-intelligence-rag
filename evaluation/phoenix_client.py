"""Small authenticated Phoenix REST client used only by offline workers.

The answer service never imports or calls this client. Phoenix availability is
therefore irrelevant to production answer latency and correctness.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen


@dataclass(frozen=True)
class PhoenixClient:
    url: str
    api_key: str = ""
    timeout_seconds: float = 10.0

    def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            f"{self.url.rstrip('/')}{path}",
            data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
            headers=headers,
            method=method,
        )
        with urlopen(request, timeout=self.timeout_seconds) as response:
            body = response.read()
            if not body:
                return {}
            value = json.loads(body)
            # Phoenix 20.5's dataset upload route documents an object response
            # but returns JSON null in some successful deployments.
            if value is None:
                return {}
            if not isinstance(value, dict):
                raise RuntimeError("Phoenix returned a non-object response")
            return value

    def upload_dataset(
        self,
        *,
        name: str,
        description: str,
        metadata: dict[str, Any],
        examples: list[dict[str, Any]],
        action: str = "create",
    ) -> dict[str, Any]:
        response = self._request(
            "POST",
            "/v1/datasets/upload",
            {
                "name": name,
                "action": action,
                "description": description,
                "inputs": [example["inputs"] for example in examples],
                "outputs": [example.get("outputs", {}) for example in examples],
                "metadata": [
                    {**example.get("metadata", {}), "dataset_metadata": metadata}
                    for example in examples
                ],
                "splits": [example.get("splits", []) for example in examples],
            },
        )
        if response:
            return response
        match = None
        for _ in range(20):
            matches = self.list_datasets(name=name).get("data", [])
            match = next((item for item in matches if item.get("name") == name), None)
            if match:
                break
            time.sleep(0.1)
        if not match:
            raise RuntimeError(f"Phoenix accepted dataset {name} but did not return it")
        return {"data": {"dataset_id": match["id"], "version_id": None}}

    def get_dataset_examples(
        self, dataset_id: str, *, version_id: str | None = None
    ) -> dict[str, Any]:
        suffix = f"?version_id={quote(version_id, safe='')}" if version_id else ""
        return self._request(
            "GET", f"/v1/datasets/{quote(dataset_id, safe='')}/examples{suffix}"
        )

    def list_datasets(self, *, name: str | None = None) -> dict[str, Any]:
        suffix = f"?name={quote(name, safe='')}" if name else ""
        return self._request("GET", f"/v1/datasets{suffix}")

    def create_experiment(
        self, dataset_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/v1/datasets/{quote(dataset_id, safe='')}/experiments", payload
        )

    def create_experiment_run(
        self, experiment_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request(
            "POST", f"/v1/experiments/{quote(experiment_id, safe='')}/runs", payload
        )

    def upsert_experiment_evaluation(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._request("POST", "/v1/experiment_evaluations", payload)

    def create_prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request("POST", "/v1/prompts", payload)


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
    api_key: str = "",
) -> None:
    """Attach aggregate scores and safe metadata to an existing Phoenix span."""

    if not url or not span_id:
        return
    annotations = []
    for name, value in scores.items():
        metric_sample_count = sample_counts.get(name, sample_count) if sample_counts else sample_count
        annotations.append(
            {
                "name": f"{section}.{name}",
                "annotator_kind": annotator_kind,
                "span_id": span_id,
                "identifier": f"{section}.{name}",
                "result": {"score": value},
                "metadata": {
                    "evaluator": "ragas" if annotator_kind == "LLM" else "deterministic",
                    "sample_count": metric_sample_count,
                    "quality_section": section,
                    **(metadata or {}),
                },
            }
        )
    body = json.dumps({"data": annotations}).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = Request(
        f"{url.rstrip('/')}/v1/span_annotations?sync=true",
        data=body,
        headers=headers,
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
