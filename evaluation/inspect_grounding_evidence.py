"""Measure whether table linearisation is what a rejected claim was missing.

Run this on the machine that has the reranker weights and MPS. It scores one or
more claims against the live retrieved evidence twice -- once against the raw
Markdown, once against the linearised form -- and prints both numbers next to the
threshold that will be applied. If the linearised column clears the threshold
where the raw column does not, the rejection was a formatting artefact, and
PI_RAG_LINEARIZE_TABLE_EVIDENCE is the fix. If neither clears it, the evidence
genuinely does not support the claim and no threshold should be moved.

    cd ~/Desktop/project-intelligence-rag
    .venv/bin/python -m evaluation.inspect_grounding_evidence \
        --chroma-host project-intelligence-v2-4kvakfy.svc.aped-4627-b74a.chroma.io \
        --question "POS_CLOSE_SHIFT_EVENT what does this event require?" \
        --claim "The shift summary carries a tickets count member." \
        --source-type PAGE
"""

from __future__ import annotations

import argparse
import asyncio

from app.config import Settings
from app.embedding import build_embedder
from app.reranking import normalized_relevance_score, predict_local_scores, sanitize_evidence
from app.retrieval import ChromaAccessRetriever
from app.table_evidence import contains_table, linearize_tables


async def _scores(settings: Settings, pairs: list[tuple[str, str]]) -> list[float]:
    if not pairs:
        return []
    raw = await asyncio.to_thread(
        predict_local_scores,
        settings.local_models_path or settings.local_rerank_model,
        device=settings.local_rerank_device,
        revision=settings.local_rerank_revision,
        pairs=pairs,
    )
    return [normalized_relevance_score(float(value)) for value in raw]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-host", required=True)
    parser.add_argument("--chroma-port", type=int, default=8000)
    parser.add_argument("--collection-name", default="project-intelligence")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--claim",
        action="append",
        required=True,
        help="A sentence the answer would assert. Repeat for several claims.",
    )
    parser.add_argument("--source-type", action="append", choices=("CODE", "PAGE", "ISSUE"), default=[])
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
        # Match the production local embedding path exactly.
        embedder=build_embedder(settings),
    )
    documents = await retriever.ainvoke_scoped(
        arguments.question, tuple(arguments.source_type)
    )
    tabular = sum(1 for document in documents if contains_table(document.page_content))
    threshold = settings.grounding_score_threshold
    table_threshold = settings.grounding_table_evidence_score_threshold

    print(f"question        : {arguments.question}")
    print(f"retrieved       : {len(documents)} chunks, {tabular} containing a table")
    print(f"threshold       : {threshold}")
    print(f"table threshold : {table_threshold if table_threshold is not None else 'unset (uses the normal threshold)'}")
    print(f"linearisation   : {'on' if settings.linearize_table_evidence else 'off'}")
    if not documents:
        print("\nNothing was retrieved, so grounding never ran. This is an indexing problem.")
        return

    for claim in arguments.claim:
        raw = await _scores(
            settings, [(claim, sanitize_evidence(d.page_content)) for d in documents]
        )
        flat = await _scores(
            settings,
            [(claim, linearize_tables(sanitize_evidence(d.page_content))) for d in documents],
        )
        ranked = sorted(
            zip(documents, raw, flat, strict=True), key=lambda row: max(row[1], row[2]), reverse=True
        )
        print(f"\n=== claim: {claim}")
        print(f"{'raw':>7} {'linear':>7} {'delta':>7}  table  title")
        for document, raw_score, flat_score in ranked[:5]:
            title = str(document.metadata.get("title") or "untitled")[:52]
            marker = " yes " if contains_table(document.page_content) else "  no "
            print(
                f"{raw_score:7.3f} {flat_score:7.3f} {flat_score - raw_score:+7.3f} {marker}  {title}"
            )
        best_raw = max(raw)
        best_flat = max(flat)
        applied = (
            table_threshold
            if table_threshold is not None and tabular
            else threshold
        )
        if best_flat >= applied and best_raw < applied:
            verdict = "linearisation is what this claim was missing"
        elif best_flat >= applied:
            verdict = "supported either way"
        else:
            verdict = "still short of the threshold -- check the evidence, not the threshold"
        print(f"  best raw {best_raw:.3f} | best linearised {best_flat:.3f} | applied {applied} -> {verdict}")


if __name__ == "__main__":
    asyncio.run(main())
