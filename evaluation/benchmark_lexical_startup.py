"""Measure startup lexical warming and the first request admitted after readiness."""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

from app.config import Settings
from app.embedding import build_embedder
from app.retrieval import ChromaAccessRetriever, warm_authorized_lexical_corpora


def _retriever(settings: Settings, project_id: str) -> ChromaAccessRetriever:
    return ChromaAccessRetriever.create(
        chroma_host=settings.chroma_host,
        chroma_port=settings.chroma_port,
        collection_name=settings.chroma_collection,
        text_field="chunk_text",
        project_id=project_id,
        access_policy_ids=(f"project:{project_id}",),
        top_k=settings.retrieval_top_k,
        score_threshold=settings.retrieval_score_threshold,
        required_schema_version=settings.supported_schema_versions[0],
        required_embedding_model=settings.supported_embedding_models[0],
        retry_attempts=settings.dependency_retry_attempts,
        timeout_seconds=settings.dependency_timeout_seconds,
        lexical_fallback_enabled=settings.lexical_fallback_enabled,
        lexical_fallback_max_records=settings.lexical_fallback_max_records,
        lexical_fallback_cache_ttl_seconds=settings.lexical_fallback_cache_ttl_seconds,
        vocabulary_cache_ttl_seconds=settings.vocabulary_cache_ttl_seconds,
        embedder=build_embedder(settings),
    )


async def _main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("question")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--chroma-host", default="127.0.0.1")
    parser.add_argument("--chroma-port", type=int, default=8000)
    arguments = parser.parse_args()
    settings = Settings(
        chroma_host=arguments.chroma_host,
        chroma_port=arguments.chroma_port,
    )

    began = time.perf_counter()
    warmed_projects = await warm_authorized_lexical_corpora(
        settings, build_embedder(settings)
    )
    warm_ms = (time.perf_counter() - began) * 1000

    retriever = _retriever(settings, arguments.project_id)
    timings: list[float] = []
    result_counts: list[int] = []
    for _ in range(max(2, arguments.runs)):
        began = time.perf_counter()
        results = await retriever.ainvoke_lexical(arguments.question)
        timings.append((time.perf_counter() - began) * 1000)
        result_counts.append(len(results))

    steady_ms = statistics.median(timings[1:])
    print(
        json.dumps(
            {
                "warmed_projects": warmed_projects,
                "startup_warm_ms": round(warm_ms, 2),
                "first_after_ready_ms": round(timings[0], 2),
                "steady_median_ms": round(steady_ms, 2),
                "first_to_steady_ratio": round(timings[0] / steady_ms, 3),
                "timings_ms": [round(value, 2) for value in timings],
                "result_counts": result_counts,
            },
            separators=(",", ":"),
        )
    )


if __name__ == "__main__":
    asyncio.run(_main())
