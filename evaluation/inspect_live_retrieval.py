"""Inspect content-free retrieval/rerank scores for one live question."""

from __future__ import annotations

import argparse
import asyncio

from app.config import Settings
from app.embedding import build_embedder
from app.reranking import normalized_relevance_score, predict_local_scores
from app.retrieval import ChromaAccessRetriever


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-host", required=True)
    parser.add_argument("--chroma-port", type=int, default=8000)
    parser.add_argument("--collection-name", default="project-intelligence")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--claim")
    parser.add_argument("--show-content-title", action="append", default=[])
    parser.add_argument(
        "--source-type",
        action="append",
        choices=("CODE", "PAGE", "ISSUE"),
        default=[],
    )
    parser.add_argument("--limit", type=int, default=25)
    arguments = parser.parse_args()
    settings = Settings()
    retriever = ChromaAccessRetriever.create(
        chroma_host=arguments.chroma_host,
        chroma_port=arguments.chroma_port,
        collection_name=arguments.collection_name,
        text_field="chunk_text",
        project_id=arguments.project_id,
        access_policy_ids=(f"project:{arguments.project_id}",),
        top_k=min(arguments.limit, 50),
        score_threshold=0.0,
        required_schema_version="3",
        required_embedding_model="multilingual-e5-large",
        retry_attempts=settings.dependency_retry_attempts,
        timeout_seconds=settings.dependency_timeout_seconds,
        # The production path always embeds locally with the same model as ingestion.
        embedder=build_embedder(settings),
    )
    documents = await retriever.ainvoke_scoped(
        arguments.question, tuple(arguments.source_type)
    )
    raw_scores = await asyncio.to_thread(
        predict_local_scores,
        settings.local_models_path or settings.local_rerank_model,
        device=settings.local_rerank_device,
        revision=settings.local_rerank_revision,
        pairs=[(arguments.question, document.page_content) for document in documents],
    )
    claim_scores = None
    if arguments.claim:
        claim_scores = await asyncio.to_thread(
            predict_local_scores,
            settings.local_models_path or settings.local_rerank_model,
            device=settings.local_rerank_device,
            revision=settings.local_rerank_revision,
            pairs=[(arguments.claim, document.page_content) for document in documents],
        )
    ranked = sorted(
        zip(documents, raw_scores, strict=True),
        key=lambda pair: normalized_relevance_score(float(pair[1])),
        reverse=True,
    )
    claim_by_chunk = (
        {
            str(document.metadata.get("chunk_id")): normalized_relevance_score(float(score))
            for document, score in zip(documents, claim_scores, strict=True)
        }
        if claim_scores is not None
        else {}
    )
    for document, raw_score in ranked:
        claim_value = claim_by_chunk.get(str(document.metadata.get("chunk_id")))
        print(
            "\t".join(
                (
                    f"rerank={normalized_relevance_score(float(raw_score)):.4f}",
                    f"retrieval={float(document.metadata.get('score') or 0):.4f}",
                    f"claim={claim_value:.4f}" if claim_value is not None else "claim=n/a",
                    f"source_type={document.metadata.get('source_type')}",
                    f"provider={document.metadata.get('provider')}",
                    f"title={document.metadata.get('title')}",
                    f"repository={document.metadata.get('repository')}",
                    f"branch={document.metadata.get('branch')}",
                    f"file={document.metadata.get('path')}",
                    f"symbol={document.metadata.get('symbol')}",
                    f"ordinal={document.metadata.get('chunk_ordinal')}",
                    f"path={' > '.join(document.metadata.get('structure_path') or [])}",
                )
            ),
            flush=True,
        )
        if (
            arguments.show_content_title
            and document.metadata.get("title") in arguments.show_content_title
        ):
            print(
                "CONTENT_PREVIEW="
                + document.page_content[:1200].replace("\n", " | ")
            )


if __name__ == "__main__":
    asyncio.run(main())
