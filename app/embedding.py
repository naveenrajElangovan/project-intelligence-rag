"""Local multilingual query embedding for Chroma retrieval.

E5 models are asymmetric: the query side must be prefixed `query: ` and the
document side `passage: `. The ingestion service owns the passage side; this
module owns the query side only, so the two prefixes can never be confused.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any

from app.config import Settings


_QUERY_PREFIX = "query: "

# E5 was trained at 512 positions. Longer text is truncated by the model, which is
# Both ingestion and retrieval enforce this same model limit.
_MAX_SEQUENCE_LENGTH = 512

# Query texts repeat across a request's retrieval attempts, not across users, so a
# small cache is enough and keeps no meaningful history.
_CACHE_ENTRIES = 64

_MODELS: dict[tuple[str, str], Any] = {}
_MODELS_LOCK = threading.Lock()

# Serializes MPS work inside this process. The reranker holds a sibling lock; the
# LangGraph retrieve and rerank nodes are sequential, so the two never contend.
_INFERENCE_LOCK = threading.Lock()


class LocalMultilingualEmbedder:
    """Embeds queries with the pinned local E5 model on the configured device."""

    def __init__(
        self,
        model: str,
        *,
        device: str,
        model_path: str = "",
        revision: str = "",
        dimensions: int = 1024,
        batch_size: int = 16,
    ) -> None:
        self._model_ref = model_path or model
        self._device = device
        self._revision = revision
        self._dimensions = dimensions
        self._batch_size = max(1, batch_size)
        # The workflow re-retrieves on a completeness repair and on a query
        # recovery, with the same query text. Embedding is deterministic, so the
        # second pass can be free. Bounded because an embedder outlives a request.
        # Guarded because query variants are retrieved concurrently on real threads,
        # and an OrderedDict mutated from several of them can corrupt.
        self._cache: OrderedDict[str, list[float]] = OrderedDict()
        self._cache_lock = threading.Lock()

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def embed_query(self, text: str) -> list[float]:
        """Return one normalized query vector, or raise if the model misconfigures."""

        return self.embed_queries([text])[0]

    def embed_queries(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        normalized = [value.strip() for value in texts]
        with self._cache_lock:
            missing = [
                value for value in dict.fromkeys(normalized) if value not in self._cache
            ]
        if missing:
            self._encode(missing)
        with self._cache_lock:
            # A concurrent caller may have evicted an entry between the encode and
            # this read, so fall back to encoding rather than raising a KeyError.
            absent = [value for value in normalized if value not in self._cache]
        if absent:
            self._encode(absent)
        with self._cache_lock:
            for value in normalized:
                if value in self._cache:
                    self._cache.move_to_end(value)
            vectors = [list(self._cache[value]) for value in normalized]
            self._evict_locked()
        return vectors

    def _evict_locked(self) -> None:
        """Drop the least recently used entries. Caller holds the cache lock."""

        while len(self._cache) > _CACHE_ENTRIES:
            self._cache.popitem(last=False)

    def _encode(self, texts: list[str]) -> None:
        model = _load_embedding_model(self._model_ref, self._device, self._revision)
        prefixed = [_QUERY_PREFIX + value for value in texts]
        with _INFERENCE_LOCK:
            vectors = model.encode(
                prefixed,
                batch_size=min(self._batch_size, len(prefixed)),
                normalize_embeddings=True,
                show_progress_bar=False,
                convert_to_numpy=True,
            )
        embedded = [[float(value) for value in vector] for vector in vectors]
        for vector in embedded:
            if len(vector) != self._dimensions:
                raise ValueError(
                    "The local embedding model produced "
                    f"{len(vector)} dimensions but the index expects {self._dimensions}. "
                    "Query and index vectors must come from the same model."
                )
        with self._cache_lock:
            for text, vector in zip(texts, embedded, strict=True):
                self._cache[text] = vector
            self._evict_locked()


def build_embedder(settings: Settings) -> LocalMultilingualEmbedder:
    """Build the mandatory local query embedder."""
    return LocalMultilingualEmbedder(
        settings.local_embedding_model,
        device=settings.local_embedding_device,
        model_path=settings.local_embedding_path,
        revision=settings.local_embedding_revision,
        dimensions=settings.embedding_dimensions,
        batch_size=settings.local_embedding_batch_size,
    )


def _load_embedding_model(model_ref: str, device: str, revision: str):
    expanded = Path(model_ref).expanduser()
    resolved = str(expanded) if expanded.exists() else model_ref
    key = (resolved + "@" + revision, device)
    with _MODELS_LOCK:
        if key in _MODELS:
            return _MODELS[key]
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise RuntimeError(
                "Local embedding requires the sentence-transformers runtime."
            ) from error
        model = SentenceTransformer(
            resolved,
            device=device,
            trust_remote_code=False,
            local_files_only=True,
            revision=None if Path(resolved).exists() else revision,
        )
        model.max_seq_length = _MAX_SEQUENCE_LENGTH
        _MODELS[key] = model
        return model


def warm_embedder(embedder: LocalMultilingualEmbedder | None) -> None:
    """Load weights at startup so the first real question does not pay for it."""

    if embedder is not None:
        embedder.embed_query("warmup")
