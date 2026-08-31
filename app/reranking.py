from __future__ import annotations

import asyncio
import math
from pathlib import Path
import re
import threading
from typing import Any

from langchain_core.documents import Document

from app.config import Settings
from app.workflow_support.filtering import preserve_non_empty
from app.retry import with_transient_retry
from app.table_evidence import linearize_tables


# Chosen so a full 50-candidate rerank is two MPS round trips rather than seven.
_DEFAULT_BATCH_SIZE = 32

_LOCAL_MODELS: dict[tuple[str, str], Any] = {}
_LOCAL_MODELS_LOCK = threading.Lock()
_LOCAL_INFERENCE_LOCK = threading.Lock()


def progressive_rerank_candidates(
    documents: list[Document], limit: int
) -> list[Document]:
    """Narrow with cheap signals while retaining anchors and source diversity."""

    if limit <= 0 or len(documents) <= limit:
        return list(documents)

    def score(item: tuple[int, Document]) -> tuple[float, ...]:
        index, document = item
        metadata = document.metadata
        primary_rank = int(metadata.get("primary_query_rank") or 0)
        return (
            1.0 if metadata.get("identifier_anchor") else 0.0,
            1.0 if primary_rank else 0.0,
            float(-primary_rank) if primary_rank else float("-inf"),
            float(metadata.get("retrieval_fused_score", 0.0) or 0.0),
            float(metadata.get("fusion_score", 0.0) or 0.0),
            float(metadata.get("lexical_score", 0.0) or 0.0),
            float(metadata.get("score", 0.0) or 0.0),
            float(-index),
        )

    ranked = [
        document
        for _, document in sorted(enumerate(documents), key=score, reverse=True)
    ]
    selected: list[Document] = []
    selected_ids: set[str] = set()

    def add(document: Document) -> None:
        identity = str(
            document.metadata.get("chunk_id")
            or document.metadata.get("source_id")
            or document.id
            or document.page_content
        )
        if identity not in selected_ids and len(selected) < limit:
            selected.append(document)
            selected_ids.add(identity)

    for document in ranked:
        if document.metadata.get("identifier_anchor") or document.metadata.get(
            "primary_query_rank"
        ):
            add(document)

    represented_types: set[str] = set()
    for document in ranked:
        source_type = str(document.metadata.get("source_type", "UNKNOWN"))
        if source_type not in represented_types:
            add(document)
            represented_types.add(source_type)

    for document in ranked:
        add(document)

    return selected


class LocalMultilingualReranker:
    """Offline cross-encoder reranking; model artifacts must already be present."""

    def __init__(
        self,
        model: str,
        *,
        device: str,
        model_path: str,
        revision: str,
        top_n: int,
        score_threshold: float,
        exact_code_score_threshold: float,
        exact_code_retrieval_score_floor: float,
        max_chunks_per_source: int,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        linearize_table_evidence: bool = True,
    ) -> None:
        self._linearize_table_evidence = linearize_table_evidence
        self._model_ref = model_path or model
        self._device = device
        self._revision = revision
        self._batch_size = batch_size
        self._top_n = top_n
        self._threshold = score_threshold
        self._exact_code_threshold = exact_code_score_threshold
        self._exact_code_retrieval_floor = exact_code_retrieval_score_floor
        self._max_chunks_per_source = max_chunks_per_source
        self.last_retry_count = 0
        self.last_capped_by_source_limit = 0
        self.last_source_cap_bypassed = False

    async def rerank(
        self,
        query: str,
        documents: list[Document],
        *,
        score_threshold: float | None = None,
        top_n: int | None = None,
        max_chunks_per_source: int | None = None,
    ) -> list[Document]:
        if not documents:
            return []
        threshold = self._threshold if score_threshold is None else score_threshold
        result_limit = self._top_n if top_n is None else max(1, top_n)
        source_limit = (
            self._max_chunks_per_source
            if max_chunks_per_source is None
            else max(1, max_chunks_per_source)
        )
        self.last_capped_by_source_limit = 0
        self.last_source_cap_bypassed = False
        scores = await asyncio.to_thread(self._predict, query, documents)
        scored: list[tuple[float, Document, str]] = []
        for document, raw_score in zip(documents, scores, strict=True):
            score = normalized_relevance_score(float(raw_score))
            exact_code_match = (
                score >= self._exact_code_threshold
                and float(document.metadata.get("score") or 0) >= self._exact_code_retrieval_floor
                and _exact_code_anchor_match(query, document)
            )
            if score < threshold and not exact_code_match:
                continue
            source_id = str(
                document.metadata.get("source_id")
                or document.metadata.get("reference")
                or document.metadata.get("chunk_id")
            )
            scored.append((score, document, source_id))

        ranked: list[Document] = []
        source_counts: dict[str, int] = {}
        for score, document, source_id in sorted(scored, key=lambda item: item[0], reverse=True):
            if source_counts.get(source_id, 0) >= source_limit:
                self.last_capped_by_source_limit += 1
                continue
            source_counts[source_id] = source_counts.get(source_id, 0) + 1
            document.metadata["rerank_score"] = score
            ranked.append(document)
            if len(ranked) >= result_limit:
                break
        if scored:
            uncapped = [document for _, document, _ in scored][:result_limit]
            ranked, self.last_source_cap_bypassed = preserve_non_empty(
                uncapped, ranked
            )
        return ranked

    def _predict(self, query: str, documents: list[Document]):
        pairs = [
            (
                query,
                scoring_evidence(
                    document.page_content,
                    linearize_tables_enabled=self._linearize_table_evidence,
                ),
            )
            for document in documents
        ]
        return predict_local_scores(
            self._model_ref,
            device=self._device,
            revision=self._revision,
            pairs=pairs,
            batch_size=self._batch_size,
        )


def build_reranker(settings: Settings):
    return LocalMultilingualReranker(
        settings.local_rerank_model,
        device=settings.local_rerank_device,
        model_path=settings.local_models_path,
        revision=settings.local_rerank_revision,
        top_n=settings.rerank_top_n,
        score_threshold=settings.rerank_score_threshold,
        exact_code_score_threshold=settings.exact_code_rerank_score_threshold,
        exact_code_retrieval_score_floor=settings.exact_code_retrieval_score_floor,
        max_chunks_per_source=settings.max_chunks_per_source,
        batch_size=settings.local_rerank_batch_size,
        linearize_table_evidence=settings.linearize_table_evidence,
    )


def _load_local_model(model_ref: str, device: str, revision: str):
    expanded = Path(model_ref).expanduser()
    resolved = str(expanded) if expanded.exists() else model_ref
    key = (resolved + "@" + revision, device)
    with _LOCAL_MODELS_LOCK:
        if key in _LOCAL_MODELS:
            return _LOCAL_MODELS[key]
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as error:
            raise RuntimeError(
                "Local reranking requires the sentence-transformers runtime."
            ) from error
        model = CrossEncoder(
            resolved,
            device=device,
            trust_remote_code=False,
            local_files_only=True,
            revision=None if Path(resolved).exists() else revision,
        )
        _LOCAL_MODELS[key] = model
        return model


def predict_local_scores(
    model_ref: str,
    *,
    device: str,
    revision: str,
    pairs: list[tuple[str, str]],
    batch_size: int = _DEFAULT_BATCH_SIZE,
):
    """Score text pairs with the pinned local cross-encoder and shared inference lock.

    The batch size matters more than it looks. A candidate pool of 50 at batch 8 is
    seven sequential MPS round trips; the GPU is idle between them, so a larger
    batch is close to free until memory binds.
    """

    if not pairs:
        return []
    model = _load_local_model(model_ref, device, revision)
    with _LOCAL_INFERENCE_LOCK:
        return model.predict(
            pairs,
            batch_size=min(batch_size, len(pairs)),
            show_progress_bar=False,
            activation_fn=_identity_activation(),
        )


def normalized_relevance_score(raw_score: float) -> float:
    """Convert a raw cross-encoder logit to a stable monotonic probability."""

    if math.isnan(raw_score):
        raise ValueError("A reranker score cannot be NaN.")
    if raw_score >= 0:
        return 1 / (1 + math.exp(-raw_score))
    exponential = math.exp(raw_score)
    return exponential / (1 + exponential)


def _identity_activation():
    from torch import nn

    return nn.Identity()


def sanitize_evidence(value: str) -> str:
    return "".join(
        character for character in value if character in "\n\t" or ord(character) >= 32
    )[:16000]


def scoring_evidence(value: str, *, linearize_tables_enabled: bool = True) -> str:
    """Evidence prepared for the cross-encoder rather than for the generator.

    The generator sees the original Markdown so it can reproduce a table. The
    cross-encoder was trained on running text and cannot recover a cell's meaning
    from its column position, so it sees one sentence per row instead.
    """

    cleaned = sanitize_evidence(value)
    return linearize_tables(cleaned) if linearize_tables_enabled else cleaned


def _exact_code_anchor_match(query: str, document: Document) -> bool:
    anchors = {
        value.casefold()
        for value in re.findall(
            r"(?:[A-Za-z0-9_.-]+/)*[A-Za-z0-9_.-]+\.(?:kt|kts|java|py|js|ts|tsx|jsx|xml|yaml|yml|json|toml|gradle)",
            query,
            flags=re.IGNORECASE,
        )
    }
    if not anchors or str(document.metadata.get("source_type") or "").upper() != "CODE":
        return False
    haystack = "\n".join(
        (
            str(document.metadata.get("title") or ""),
            str(document.metadata.get("reference") or ""),
            document.page_content[:2000],
        )
    ).casefold()
    return any(anchor in haystack for anchor in anchors)
