"""Small authenticated MPS inference service for a Dockerized RAG API."""

from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from app.config import Settings, get_settings
from app.embedding import LocalMultilingualEmbedder
from app.reranking import predict_local_scores


class EmbedRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=32)


class RerankPair(BaseModel):
    query: str = Field(min_length=1, max_length=4_000)
    evidence: str = Field(min_length=1, max_length=16_000)


class RerankRequest(BaseModel):
    pairs: list[RerankPair] = Field(min_length=1, max_length=64)
    max_length: int = Field(default=1024, ge=256, le=8192)


def require_accelerator_caller(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.internal_api_key
    if (
        not expected
        or not authorization
        or not authorization.startswith("Bearer ")
        or not hmac.compare_digest(authorization[7:], expected)
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid accelerator credential.")


def _embedder(settings: Settings) -> LocalMultilingualEmbedder:
    return LocalMultilingualEmbedder(
        settings.local_embedding_model,
        device=settings.local_embedding_device,
        model_path=settings.local_embedding_path,
        revision=settings.local_embedding_revision,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.local_embedding_batch_size,
    )


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings = get_settings()
    embedder = _embedder(settings)
    await asyncio.to_thread(embedder.embed_query, "warmup")
    await asyncio.to_thread(
        predict_local_scores,
        settings.local_models_path or settings.local_rerank_model,
        device=settings.local_rerank_device,
        revision=settings.local_rerank_revision,
        pairs=[("project knowledge", "Project knowledge warm-up sample.")],
        batch_size=1,
        max_length=settings.local_rerank_max_length,
    )
    application.state.embedder = embedder
    yield


app = FastAPI(title="Project Intelligence Local Accelerator", lifespan=lifespan)


@app.get("/health", dependencies=[Depends(require_accelerator_caller)])
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/embed", dependencies=[Depends(require_accelerator_caller)])
async def embed(request: EmbedRequest) -> dict[str, list[list[float]]]:
    vectors = await asyncio.to_thread(app.state.embedder.embed_queries, request.texts)
    return {"vectors": vectors}


@app.post("/rerank", dependencies=[Depends(require_accelerator_caller)])
async def rerank(
    request: RerankRequest, settings: Settings = Depends(get_settings)
) -> dict[str, list[float]]:
    scores = await asyncio.to_thread(
        predict_local_scores,
        settings.local_models_path or settings.local_rerank_model,
        device=settings.local_rerank_device,
        revision=settings.local_rerank_revision,
        pairs=[(pair.query, pair.evidence) for pair in request.pairs],
        batch_size=settings.local_rerank_batch_size,
        max_length=request.max_length,
    )
    return {"scores": [float(value) for value in scores]}
