"""Answer one question: can this corpus page be retrieved for this question at all?

A page can be missing from an answer for four different reasons, and they need
different fixes:

  1. it was never indexed                      -> ingestion problem
  2. it was indexed but the source scope        -> intent routing problem
     excludes its source type
  3. it is in the candidate set but ranks       -> retrieval/fusion problem
     below the window the reranker sees
  4. it is reranked in, and grounding rejects   -> verification problem
     the claims written from it

This prints which one it is. Run it on the machine holding the model weights:

    cd ~/Desktop/project-intelligence-rag
    .venv/bin/python -m evaluation.inspect_page_reachability \
        --chroma-host project-intelligence-v2-4kvakfy.svc.aped-4627-b74a.chroma.io \
        --question "POS_CLOSE_SHIFT_EVENT what does this event require?" \
        --expect-title "Event and Integration Contract"
"""

from __future__ import annotations

import argparse
import asyncio

from app.config import Settings
from app.embedding import build_embedder
from app.reranking import build_reranker
from app.retrieval import ChromaAccessRetriever
from app.retrieval_pipeline import BM25Retriever, ReciprocalRankFusion
from app.workflow_support.query_analysis import _intent_source_scope, _source_route_intent


def _matches(document, needle: str) -> bool:
    haystack = " ".join(
        str(document.metadata.get(field) or "")
        for field in ("title", "reference", "source_url", "structure_path")
    )
    return needle.casefold() in haystack.casefold()


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma-host", required=True)
    parser.add_argument("--chroma-port", type=int, default=8000)
    parser.add_argument("--collection-name", default="project-intelligence")
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument(
        "--expect-title",
        required=True,
        help="A substring of the title/reference of the page that should answer this.",
    )
    arguments = parser.parse_args()

    settings = Settings()
    intent = _source_route_intent(arguments.question)
    scope, route = _intent_source_scope(intent)
    print(f"question : {arguments.question}")
    print(f"intent   : {intent}  scope={scope or '(no filter)'}  route={route}")

    retriever = ChromaAccessRetriever.create(
        chroma_host=arguments.chroma_host,
        chroma_port=arguments.chroma_port,
        collection_name=arguments.collection_name,
        text_field="chunk_text",
        project_id=arguments.project_id,
        access_policy_ids=(f"project:{arguments.project_id}",),
        top_k=settings.retrieval_top_k,
        score_threshold=settings.retrieval_score_threshold,
        required_schema_version="3",
        required_embedding_model="multilingual-e5-large",
        retry_attempts=settings.dependency_retry_attempts,
        timeout_seconds=settings.dependency_timeout_seconds,
        embedder=build_embedder(settings),
    )

    dense = await retriever.ainvoke_scoped(arguments.question, tuple(scope))
    fell_back = any(d.metadata.get("retrieval_fallback") for d in dense)
    print(f"\nretrieved: {len(dense)} chunks"
          + ("  *** LEXICAL FALLBACK -- dense retrieval failed, see the log line above ***"
             if fell_back else ""))

    hits = [(rank, d) for rank, d in enumerate(dense, start=1) if _matches(d, arguments.expect_title)]
    if not hits:
        print(f"\n[1/2] The expected page is NOT in the dense candidate set.")
        print("      Either it was never indexed, or the source scope above excludes it,")
        print("      or the embedding simply does not associate it with this wording.")
    else:
        print(f"\n[ok] The expected page IS in the candidate set, at dense ranks:")
        for rank, document in hits[:5]:
            print(f"     #{rank:<3} score={float(document.metadata.get('score') or 0):.4f}"
                  f"  {str(document.metadata.get('structure_path') or '')[:70]}")

    lexical = BM25Retriever().rank(arguments.question, list(dense))
    lexical_ranks = [
        rank for rank, document in enumerate(lexical, start=1)
        if _matches(document, arguments.expect_title)
    ]
    print(f"\nlexical channel: expected page at ranks {lexical_ranks[:5] or 'absent'}")

    fusion = ReciprocalRankFusion(
        k=settings.rank_fusion_k,
        lexical_weight=settings.lexical_fusion_weight,
        dense_weight=settings.dense_fusion_weight,
    )
    fused = fusion.fuse(lexical, list(dense), limit=settings.max_candidates)
    fused_ranks = [
        rank for rank, document in enumerate(fused, start=1)
        if _matches(document, arguments.expect_title)
    ]
    print(f"fused           : expected page at ranks {fused_ranks[:5] or 'absent'}"
          f" of {len(fused)} candidates")

    reranker = build_reranker(settings)
    reranked = await reranker.rerank(arguments.question, list(fused))
    reranked_ranks = [
        rank for rank, document in enumerate(reranked, start=1)
        if _matches(document, arguments.expect_title)
    ]
    print(f"reranked        : {len(reranked)} survive the window;"
          f" expected page at ranks {reranked_ranks[:5] or 'absent'}")

    print("\n--- what survives, in order ---")
    for rank, document in enumerate(reranked, start=1):
        mark = " <== expected" if _matches(document, arguments.expect_title) else ""
        print(f"  #{rank:<3} {float(document.metadata.get('rerank_score') or 0):.3f}"
              f"  {str(document.metadata.get('title') or '')[:42]:42}"
              f"  {str(document.metadata.get('structure_path') or '')[:44]}{mark}")

    print("\n--- verdict ---")
    if fell_back:
        print("Dense retrieval failed and this ran on BM25 only. Fix that first;")
        print("nothing measured below it is meaningful.")
    elif not hits:
        print("The page never entered retrieval. This is an indexing or embedding")
        print("association problem, not a grounding one.")
    elif not reranked_ranks:
        print("The page was retrieved and then dropped by fusion/rerank. This is a")
        print("ranking problem: widen the window or anchor the identifier.")
    else:
        print("The page reaches the generator. If the answer still refuses, the")
        print("failure is in grounding -- run inspect_grounding_evidence.py next.")


if __name__ == "__main__":
    asyncio.run(main())
