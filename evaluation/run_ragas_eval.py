"""Run Ragas against an explicit, controlled JSONL dataset."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
from statistics import fmean
import time
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")


REQUIRED_FIELDS = ("user_input", "response", "retrieved_contexts", "reference")


def load_samples(path: Path) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        missing = [field for field in REQUIRED_FIELDS if field not in value]
        if missing:
            raise ValueError(f"line {line_number} is missing: {', '.join(missing)}")
        if not isinstance(value["retrieved_contexts"], list):
            raise ValueError(f"line {line_number} retrieved_contexts must be a list")
        samples.append({field: value[field] for field in REQUIRED_FIELDS})
    if not samples:
        raise ValueError("the Ragas dataset is empty")
    return samples


def publish_scores_to_phoenix(
    url: str,
    span_id: str | None,
    scores: dict[str, float],
    sample_count: int,
) -> None:
    """Attach aggregate Ragas scores to their evaluation span in Phoenix."""
    if not url or not span_id:
        return
    annotations = [
        {
            "name": f"ragas.{name}",
            "annotator_kind": "LLM",
            "span_id": span_id,
            "identifier": f"ragas.{name}",
            "result": {"score": value},
            "metadata": {"evaluator": "ragas", "sample_count": sample_count},
        }
        for name, value in scores.items()
    ]
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evaluation/ragas-results.json"))
    parser.add_argument("--model", default=os.getenv("PI_RAG_RAGAS_MODEL", "qwen3.5:latest"))
    parser.add_argument(
        "--base-url",
        default=os.getenv("PI_RAG_RAGAS_BASE_URL", "http://127.0.0.1:11434/v1"),
    )
    parser.add_argument("--api-key", default=os.getenv("PI_RAG_RAGAS_API_KEY", "ollama"))
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument(
        "--include-factual-correctness",
        action="store_true",
        help="Also run the substantially slower factual-correctness judge.",
    )
    parser.add_argument(
        "--phoenix-url",
        default=os.getenv("PI_RAG_PHOENIX_URL", "http://127.0.0.1:6006"),
    )
    args = parser.parse_args()

    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import Faithfulness, FactualCorrectness, LLMContextRecall

    from app.config import get_settings
    from app.openinference_tracing import configure_openinference

    os.environ.setdefault("PI_RAG_OPENINFERENCE_ENABLED", "true")
    os.environ.setdefault(
        "PI_RAG_OPENINFERENCE_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces"
    )
    tracer_provider = configure_openinference(get_settings())
    try:
        samples = load_samples(args.input)
        evaluator = LangchainLLMWrapper(
            ChatOpenAI(
                model=args.model,
                base_url=args.base_url,
                api_key=args.api_key,
                temperature=0,
                max_tokens=1024,
                timeout=args.timeout,
                extra_body={"think": False},
            )
        )
        metrics = [LLMContextRecall(), Faithfulness()]
        if args.include_factual_correctness:
            metrics.append(FactualCorrectness())
        tracer = tracer_provider.get_tracer("project-intelligence-ragas") if tracer_provider else None
        evaluation_scope = (
            tracer.start_as_current_span(
                "ragas.evaluate",
                attributes={
                    "openinference.span.kind": "CHAIN",
                    "ragas.evaluation": "true",
                    "ragas.sample_count": len(samples),
                },
            )
            if tracer
            else nullcontext(None)
        )
        with evaluation_scope as evaluation_span:
            result = evaluate(
                dataset=EvaluationDataset.from_list(samples),
                metrics=metrics,
                llm=evaluator,
                run_config=RunConfig(timeout=args.timeout, max_workers=1),
                raise_exceptions=True,
            )
            span_id = (
                format(evaluation_span.get_span_context().span_id, "016x")
                if evaluation_span is not None
                else None
            )
        frame = result.to_pandas()
        metric_names = ("context_recall", "faithfulness", "factual_correctness")
        scores = {
            name: fmean(float(value) for value in frame[name].dropna().tolist())
            for name in metric_names
            if name in frame and not frame[name].dropna().empty
        }
        payload = {"sample_count": len(samples), "scores": scores}
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if tracer_provider is not None:
            tracer_provider.force_flush()
        publish_scores_to_phoenix(args.phoenix_url, span_id, scores, len(samples))
        print(json.dumps(payload, indent=2))
    finally:
        if tracer_provider is not None:
            tracer_provider.shutdown()


if __name__ == "__main__":
    main()
