import asyncio

from langchain_core.documents import Document

from app.config import Settings
from app.embedding import RemoteMultilingualEmbedder, build_embedder
from app.grounding import LocalCitationGroundingVerifier
from app.llm import GroundedAnswer
from app.reranking import RemoteMultilingualReranker, build_reranker


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="development",
        internal_api_key="test-accelerator-key",
        local_accelerator_url="http://host.docker.internal:8004",
        local_models_path="/models/reranker",
        local_embedding_path="/models/embedder",
    )


def test_remote_embedder_preserves_cache_and_dimensions(monkeypatch) -> None:
    calls = []

    def embed(*args, **kwargs):
        calls.append((args, kwargs))
        return [[0.0] * 1024]

    monkeypatch.setattr("app.embedding.accelerator_embed", embed)
    embedder = build_embedder(_settings())

    assert isinstance(embedder, RemoteMultilingualEmbedder)
    assert embedder.embed_query("same query") == embedder.embed_query("same query")
    assert len(calls) == 1


def test_remote_reranker_preserves_local_selection_logic(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.reranking.accelerator_scores",
        lambda *args, **kwargs: [-2.0, 2.0],
    )
    reranker = build_reranker(_settings())
    documents = [
        Document(page_content="weak", metadata={"source_id": "one"}),
        Document(page_content="strong", metadata={"source_id": "two"}),
    ]

    ranked = asyncio.run(reranker.rerank("question", documents))

    assert isinstance(reranker, RemoteMultilingualReranker)
    assert [document.page_content for document in ranked] == ["strong", "weak"]


def test_grounding_uses_remote_scores(monkeypatch) -> None:
    calls = []

    def scores(*args, **kwargs):
        calls.append((args, kwargs))
        return [4.0]

    monkeypatch.setattr("app.grounding.accelerator_scores", scores)
    verifier = LocalCitationGroundingVerifier(_settings())
    documents = [Document(page_content="The POS accepts card payments.")]
    answer = GroundedAnswer(
        answer="The POS accepts card payments [SOURCE 1].",
        confidence="HIGH",
        citations=[1],
    )

    verdict = asyncio.run(verifier.verify("What does the POS do?", documents, answer))

    assert verdict.supported is True
    assert len(calls) == 1
