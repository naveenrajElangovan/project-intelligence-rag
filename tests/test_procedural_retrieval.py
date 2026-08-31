import asyncio

from langchain_core.documents import Document

from app.workflow_support.procedural_retrieval import (
    balanced_source_candidate_pool,
    is_procedural_question,
    rerank_source_families,
)


def _document(name: str, source_type: str, score: float) -> Document:
    return Document(
        page_content=name,
        metadata={
            "chunk_id": name,
            "source_type": source_type,
            "retrieval_fused_score": score,
        },
    )


def test_procedural_detection_is_generic() -> None:
    assert is_procedural_question("How can I login to the POS application?")
    assert is_procedural_question("What steps deploy the service?")
    assert not is_procedural_question("What is POS_LOGIN?")


def test_balanced_pool_preserves_dynamic_source_families() -> None:
    documents = [
        *[_document(f"code-{index}", "CODE", 1.0 - index / 100) for index in range(10)],
        _document("page", "PAGE", 0.2),
        _document("future", "FUTURE_SOURCE", 0.1),
    ]

    selected = balanced_source_candidate_pool(documents, 6)

    assert {item.metadata["source_type"] for item in selected} == {
        "CODE",
        "PAGE",
        "FUTURE_SOURCE",
    }


def test_source_families_are_reranked_independently_and_merged() -> None:
    class FakeReranker:
        async def rerank(self, query, documents, **kwargs):
            assert "workflow" in query
            for index, document in enumerate(documents):
                document.metadata["rerank_score"] = 1.0 - index / 10
            return list(documents)

    documents = [
        _document("event-page", "PAGE", 0.9),
        _document("login-code", "CODE", 0.4),
        _document("login-issue", "ISSUE", 0.3),
    ]

    selected = asyncio.run(
        rerank_source_families(
            FakeReranker(),
            "How can I login?",
            documents,
            top_n=3,
        )
    )

    assert {item.metadata["source_type"] for item in selected} == {
        "PAGE",
        "CODE",
        "ISSUE",
    }
