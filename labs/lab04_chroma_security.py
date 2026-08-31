"""Lab 4: observe Chroma authorization filtering and local reranking offline."""

import asyncio

from langchain_core.documents import Document

from app.reranking import LocalMultilingualReranker
from app.retrieval import ChromaAccessRetriever


class Index:
    def __init__(self) -> None:
        self.request = {}

    def query(self, **kwargs):
        self.request = kwargs
        return {
            "ids": [["c1"]],
            "distances": [[0.1]],
            "documents": [["La política pertenece al proyecto DEMO."]],
            "metadatas": [[{
                "project_id": "DEMO", "access_policy_id": "project:DEMO",
                "source_id": "spec", "title": "Security", "reference": "SEC-1",
                "language": "es",
            }]],
        }


class Embedder:
    def embed_query(self, query):
        return [0.1, 0.2]


class Reranker(LocalMultilingualReranker):
    def _predict(self, query, documents):
        return [0.91] * len(documents)


async def run() -> dict[str, object]:
    index = Index()
    retriever = ChromaAccessRetriever(
        index=index, collection_name="project-intelligence", embedder=Embedder(), project_id="DEMO",
        access_policy_ids=("project:DEMO",), top_k=25, score_threshold=0,
    )
    documents = await retriever.ainvoke("How is the policy assigned?")
    reranked = await Reranker(
        "fake", device="cpu", model_path="", revision="test", top_n=8,
        score_threshold=0, exact_code_score_threshold=1,
        exact_code_retrieval_score_floor=1, max_chunks_per_source=2,
    ).rerank("How is the policy assigned?", documents)
    return {"search": index.request, "reranked": [item.metadata["reference"] for item in reranked]}


if __name__ == "__main__":
    print(asyncio.run(run()))
