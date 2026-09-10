"""Publish one completed, content-free bilingual quality run to Phoenix."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.openinference_tracing import configure_openinference
from evaluation.phoenix_client import publish_scores_to_phoenix
from evaluation.score import (
    generation_dashboard_scores,
    generation_dashboard_sample_counts,
    retrieval_dashboard_sample_counts,
    retrieval_dashboard_scores,
)


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"quality result must be an object: {path}")
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval", type=Path)
    parser.add_argument("--answer-generation", type=Path)
    parser.add_argument("--generation-diagnostics", type=Path)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--status", choices=("completed", "failed"), default="completed")
    parser.add_argument("--failed-stage", default="")
    parser.add_argument("--dataset-version", default="1")
    parser.add_argument("--commit-sha", default="unknown")
    parser.add_argument(
        "--judge-model",
        default=os.getenv("PI_RAG_RAGAS_MODEL") or get_settings().ollama_model,
    )
    parser.add_argument("--previous-retrieval", type=Path)
    parser.add_argument("--previous-answer-generation", type=Path)
    parser.add_argument(
        "--phoenix-url",
        default=os.getenv("PI_RAG_PHOENIX_URL", "http://127.0.0.1:6006"),
    )
    parser.add_argument(
        "--otlp-endpoint",
        default=os.getenv(
            "PI_RAG_OPENINFERENCE_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces"
        ),
    )
    args = parser.parse_args()

    if args.status == "failed" and not args.failed_stage:
        parser.error("--failed-stage is required when --status failed")
    if args.status == "completed" and (
        args.retrieval is None or args.answer_generation is None
    ):
        parser.error("completed runs require --retrieval and --answer-generation")

    settings = get_settings().model_copy(
        update={
            "openinference_enabled": True,
            "openinference_otlp_endpoint": args.otlp_endpoint,
        }
    )
    provider = configure_openinference(settings)
    if provider is None:
        raise RuntimeError("OpenInference could not be configured")
    if args.status == "failed":
        try:
            tracer = provider.get_tracer("project-intelligence-quality")
            with tracer.start_as_current_span(
                "rag.quality.run",
                attributes={
                    "openinference.span.kind": "CHAIN",
                    "quality.run_id": args.run_id,
                    "quality.project_id": args.project_id,
                    "quality.status": "failed",
                    "quality.failed_stage": args.failed_stage,
                    "quality.dataset_version": args.dataset_version,
                    "quality.commit_sha": args.commit_sha,
                    "auth.boundary": f"project:{args.project_id}",
                },
            ):
                pass
            provider.force_flush()
        finally:
            provider.shutdown()
        return

    retrieval = _read(args.retrieval)
    answer = _read(args.answer_generation)
    generation_diagnostics = (
        _read(args.generation_diagnostics) if args.generation_diagnostics else None
    )
    answer_scores = answer.get("scores")
    if not isinstance(answer_scores, dict):
        raise ValueError("answer-generation result has no scores object")
    retrieval_scores = retrieval_dashboard_scores(retrieval)
    normalized_answer_scores = {
        str(name): float(value) for name, value in answer_scores.items()
    }
    if args.previous_retrieval and args.previous_retrieval.exists():
        previous = retrieval_dashboard_scores(_read(args.previous_retrieval))
        retrieval_scores.update(
            {
                f"delta_from_previous.{name}": value - previous[name]
                for name, value in retrieval_scores.items()
                if name in previous
            }
        )
    if args.previous_answer_generation and args.previous_answer_generation.exists():
        previous_payload = _read(args.previous_answer_generation).get("scores", {})
        if isinstance(previous_payload, dict):
            normalized_answer_scores.update(
                {
                    f"delta_from_previous.{name}": value - float(previous_payload[name])
                    for name, value in list(normalized_answer_scores.items())
                    if name in previous_payload
                }
            )

    common_metadata = {
        "run_id": args.run_id,
        "project_id": args.project_id,
        "dataset_version": args.dataset_version,
        "commit_sha": args.commit_sha,
        "embedding_model": settings.local_embedding_model,
        "rerank_model": settings.local_rerank_model,
        "judge_model": args.judge_model,
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "retrieval_top_k": int(retrieval.get("retrieval_top_k", settings.retrieval_top_k)),
        "rerank_top_n": int(retrieval.get("rerank_top_n", settings.rerank_top_n)),
        "retrieval_sample_count_en": int(
            (retrieval.get("by_query_language", {}) or {}).get("en", {}).get("cases", 0)
        ),
        "retrieval_sample_count_es": int(
            (retrieval.get("by_query_language", {}) or {}).get("es", {}).get("cases", 0)
        ),
        "answer_sample_count_en": int(
            (answer.get("sample_counts", {}) or {}).get("en", 0)
        ),
        "answer_sample_count_es": int(
            (answer.get("sample_counts", {}) or {}).get("es", 0)
        ),
        "generation_diagnostic_sample_count": int(
            (generation_diagnostics or {}).get("cases", 0)
        ),
    }
    try:
        tracer = provider.get_tracer("project-intelligence-quality")
        boundary = f"project:{args.project_id}"
        with tracer.start_as_current_span(
            "rag.quality.run",
            attributes={
                "openinference.span.kind": "CHAIN",
                "quality.run_id": args.run_id,
                "quality.project_id": args.project_id,
                "quality.status": "completed",
                "auth.boundary": boundary,
            },
        ):
            with tracer.start_as_current_span(
                "rag.quality.retrieval",
                attributes={"quality.section": "retrieval", "auth.boundary": boundary},
            ) as retrieval_span:
                retrieval_span_id = format(
                    retrieval_span.get_span_context().span_id, "016x"
                )
            with tracer.start_as_current_span(
                "rag.quality.answer_generation",
                attributes={"quality.section": "answer_generation", "auth.boundary": boundary},
            ) as answer_span:
                answer_span_id = format(answer_span.get_span_context().span_id, "016x")
        provider.force_flush()
        publish_scores_to_phoenix(
            args.phoenix_url,
            retrieval_span_id,
            retrieval_scores,
            int(retrieval.get("cases", 0)),
            section="retrieval",
            annotator_kind="CODE",
            metadata=common_metadata,
            sample_counts=retrieval_dashboard_sample_counts(retrieval),
        )
        publish_scores_to_phoenix(
            args.phoenix_url,
            answer_span_id,
            normalized_answer_scores,
            int(answer.get("sample_count", 0)),
            section="answer_generation",
            annotator_kind="LLM",
            metadata=common_metadata,
        )
        if generation_diagnostics is not None:
            publish_scores_to_phoenix(
                args.phoenix_url,
                answer_span_id,
                generation_dashboard_scores(generation_diagnostics),
                int(generation_diagnostics.get("cases", 0)),
                section="answer_generation",
                annotator_kind="CODE",
                metadata=common_metadata,
                sample_counts=generation_dashboard_sample_counts(
                    generation_diagnostics
                ),
            )
    finally:
        provider.shutdown()


if __name__ == "__main__":
    main()
