"""Run Ragas against an explicit, controlled JSONL dataset."""

from __future__ import annotations

import argparse
from contextlib import nullcontext
import json
import os
from pathlib import Path
from statistics import fmean
from typing import Any

from langchain_core.embeddings import Embeddings

from app.config import Settings, get_settings
from evaluation.phoenix_client import publish_scores_to_phoenix

os.environ.setdefault("RAGAS_DO_NOT_TRACK", "true")


REQUIRED_FIELDS = ("user_input", "response", "retrieved_contexts", "reference")
OPTIONAL_FIELDS = (
    "case_id",
    "query_language",
    "target_evidence_language",
    "reference_status",
    "dataset_version",
)
ANSWER_METRICS = ("faithfulness", "answer_relevancy", "answer_correctness")


class RagasMultilingualEmbeddings(Embeddings):
    """Adapt the pinned local multilingual embedder to LangChain's eval contract."""

    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Answer relevancy compares questions with generated questions, so both
        # sides intentionally use the E5 query representation.
        return self._delegate.embed_queries(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._delegate.embed_query(text)


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
        language = str(value.get("query_language") or "und")
        if language not in {"en", "es", "und"}:
            raise ValueError(f"line {line_number} has unsupported query_language: {language}")
        if value.get("reference_status") not in {None, "reviewed"}:
            raise ValueError(f"line {line_number} reference_status must be reviewed")
        samples.append(
            {
                **{field: value[field] for field in REQUIRED_FIELDS},
                **{field: value[field] for field in OPTIONAL_FIELDS if field in value},
            }
        )
    if not samples:
        raise ValueError("the Ragas dataset is empty")
    return samples


def validate_bilingual_samples(samples: list[dict[str, Any]]) -> None:
    """Require reviewed EN/ES references and all four retrieval directions."""

    duplicates = {
        case_id
        for case_id in (str(sample.get("case_id") or "") for sample in samples)
        if case_id and sum(str(item.get("case_id") or "") == case_id for item in samples) > 1
    }
    if duplicates:
        raise ValueError(f"duplicate bilingual case_id values: {sorted(duplicates)}")
    unreviewed = [
        str(sample.get("case_id") or index)
        for index, sample in enumerate(samples, 1)
        if sample.get("reference_status") != "reviewed"
    ]
    if unreviewed:
        raise ValueError(
            "bilingual RAGAS references must be human-reviewed: "
            + ", ".join(unreviewed[:10])
        )
    directions = {
        (sample.get("query_language"), sample.get("target_evidence_language"))
        for sample in samples
    }
    required = {("en", "en"), ("es", "es"), ("en", "es"), ("es", "en")}
    if not required.issubset(directions):
        missing = sorted(required - directions)
        raise ValueError(f"bilingual RAGAS dataset is missing directions: {missing}")


def aggregate_scores(
    frame: Any, samples: list[dict[str, Any]], metric_names: tuple[str, ...] = ANSWER_METRICS
) -> dict[str, float]:
    """Return overall, EN, ES, and parity-gap scores without exporting content."""

    scores: dict[str, float] = {}
    for name in metric_names:
        if name not in frame:
            continue
        values = [float(value) if value == value else None for value in frame[name].tolist()]
        overall = [value for value in values if value is not None]
        if overall:
            scores[f"{name}.overall"] = fmean(overall)
        language_scores: dict[str, float] = {}
        for language in ("en", "es"):
            selected = [
                value
                for value, sample in zip(values, samples, strict=True)
                if value is not None and sample.get("query_language") == language
            ]
            if selected:
                language_scores[language] = fmean(selected)
                scores[f"{name}.{language}"] = language_scores[language]
        if language_scores.keys() >= {"en", "es"}:
            gap = language_scores["en"] - language_scores["es"]
            scores[f"{name}.language_gap"] = gap
            scores[f"{name}.language_gap_abs"] = abs(gap)
    return scores


def build_answer_metrics(include_factual_correctness: bool = False) -> list[Any]:
    """Build the pinned RAGAS answer metric set; factual correctness is diagnostic."""

    from ragas.metrics import (
        AnswerCorrectness,
        AnswerRelevancy,
        Faithfulness,
        FactualCorrectness,
    )

    metrics: list[Any] = [Faithfulness(), AnswerRelevancy(), AnswerCorrectness()]
    if include_factual_correctness:
        metrics.append(FactualCorrectness())
    return metrics


def validate_judge_model(model: str, *, allow_floating: bool = False) -> str:
    """Reject mutable judge tags unless a caller explicitly accepts the risk."""

    resolved = model.strip()
    if not resolved:
        raise ValueError("the RAGAS judge model must not be empty")
    if resolved.casefold().endswith(":latest") and not allow_floating:
        raise ValueError(
            "the RAGAS judge model must be pinned; pass --allow-floating-judge "
            "only for an intentional non-comparable run"
        )
    return resolved


def main() -> None:
    configured_settings = Settings()
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path("evaluation/ragas-results.json"))
    parser.add_argument(
        "--model",
        default=os.getenv("PI_RAG_RAGAS_MODEL") or configured_settings.ollama_model,
    )
    parser.add_argument(
        "--allow-floating-judge",
        action="store_true",
        help="Allow a mutable :latest judge tag for an intentionally non-comparable run.",
    )
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
    parser.add_argument("--quality-run-id", default=os.getenv("PI_RAG_QUALITY_RUN_ID", ""))
    parser.add_argument("--project-id", default=os.getenv("PI_RAG_QUALITY_PROJECT_ID", ""))
    parser.add_argument("--dataset-version", default=os.getenv("PI_RAG_DATASET_VERSION", "1"))
    parser.add_argument("--commit-sha", default=os.getenv("PI_RAG_COMMIT_SHA", "unknown"))
    parser.add_argument(
        "--require-bilingual-reviewed",
        action="store_true",
        help="Reject datasets without reviewed EN/ES references in all four directions.",
    )
    args = parser.parse_args()
    args.model = validate_judge_model(
        args.model, allow_floating=args.allow_floating_judge
    )

    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, RunConfig, evaluate
    from ragas.llms import LangchainLLMWrapper
    from app.embedding import build_embedder
    from app.openinference_tracing import configure_openinference

    settings = get_settings()
    tracer_provider = None
    if args.phoenix_url:
        tracing_settings = settings.model_copy(
            update={"openinference_enabled": True}
        )
        tracer_provider = configure_openinference(tracing_settings)
    try:
        samples = load_samples(args.input)
        if args.require_bilingual_reviewed:
            validate_bilingual_samples(samples)
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
        embedding_model = RagasMultilingualEmbeddings(build_embedder(settings))
        metrics = build_answer_metrics(args.include_factual_correctness)
        tracer = tracer_provider.get_tracer("project-intelligence-ragas") if tracer_provider else None
        evaluation_scope = (
            tracer.start_as_current_span(
                "rag.quality.answer_generation",
                attributes={
                    "openinference.span.kind": "CHAIN",
                    "ragas.evaluation": "true",
                    "ragas.sample_count": len(samples),
                    "quality.section": "answer_generation",
                    "quality.run_id": args.quality_run_id or "standalone",
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
                embeddings=embedding_model,
                run_config=RunConfig(timeout=args.timeout, max_workers=1),
                raise_exceptions=True,
            )
            span_id = (
                format(evaluation_span.get_span_context().span_id, "016x")
                if evaluation_span is not None
                else None
            )
        frame = result.to_pandas()
        metric_names = ANSWER_METRICS + (("factual_correctness",) if args.include_factual_correctness else ())
        scores = aggregate_scores(frame, samples, metric_names)
        payload = {
            "section": "answer_generation",
            "sample_count": len(samples),
            "sample_counts": {
                language: sum(sample.get("query_language") == language for sample in samples)
                for language in ("en", "es")
            },
            "scores": scores,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        if tracer_provider is not None:
            tracer_provider.force_flush()
        publish_scores_to_phoenix(
            args.phoenix_url,
            span_id,
            scores,
            len(samples),
            metadata={
                "run_id": args.quality_run_id or "standalone",
                "project_id": args.project_id,
                "dataset_version": args.dataset_version,
                "commit_sha": args.commit_sha,
                "judge_model": args.model,
                "embedding_model": settings.local_embedding_model,
                "sample_count_en": sum(
                    sample.get("query_language") == "en" for sample in samples
                ),
                "sample_count_es": sum(
                    sample.get("query_language") == "es" for sample in samples
                ),
            },
        )
        print(json.dumps(payload, indent=2))
    finally:
        if tracer_provider is not None:
            tracer_provider.shutdown()


if __name__ == "__main__":
    main()
