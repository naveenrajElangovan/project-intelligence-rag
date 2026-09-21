from __future__ import annotations

import asyncio
from collections import OrderedDict
import hashlib
import json
import math
from pathlib import Path
import re
import threading
from typing import Any

from langchain_core.documents import Document

from app.config import Settings
from app.accelerator import accelerator_scores
from app.table_evidence import linearize_tables


# Chosen so a full 50-candidate rerank is two MPS round trips rather than seven.
_DEFAULT_BATCH_SIZE = 32

# Cross-encoder scores are deterministic for a (model, length, query, evidence)
# tuple, and the same tuple recurs constantly: a second retrieval attempt scores
# the candidates the first one already scored, a repair re-ranks the same
# evidence, and the project-overview route fuses several queries over one
# candidate pool. Keyed by content digest, so a chunk whose text changed is a
# different entry rather than a stale one.
_SCORE_CACHE: OrderedDict[tuple[str, int, str, str], float] = OrderedDict()
_SCORE_CACHE_LOCK = threading.Lock()
_SCORE_CACHE_ENTRIES = 8192

_LOCAL_MODELS: dict[tuple[str, str], Any] = {}
_LOCAL_MODELS_LOCK = threading.Lock()
_LOCAL_INFERENCE_LOCK = threading.Lock()


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def cached_scores(
    model_ref: str,
    max_length: int,
    pairs: list[tuple[str, str]],
    compute: Any,
) -> list[float]:
    """Score pairs, computing only the ones not already known.

    `compute` receives the uncached pairs in order and returns their scores.
    """

    keys = [(model_ref, max_length, _digest(query), _digest(evidence)) for query, evidence in pairs]
    scores: list[float | None] = [None] * len(pairs)
    pending: list[int] = []
    with _SCORE_CACHE_LOCK:
        for index, key in enumerate(keys):
            if key in _SCORE_CACHE:
                _SCORE_CACHE.move_to_end(key)
                scores[index] = _SCORE_CACHE[key]
            else:
                pending.append(index)
    if pending:
        computed = compute([pairs[index] for index in pending])
        if len(computed) != len(pending):
            raise RuntimeError("The scorer returned the wrong number of scores.")
        with _SCORE_CACHE_LOCK:
            for index, value in zip(pending, computed, strict=True):
                scores[index] = float(value)
                _SCORE_CACHE[keys[index]] = float(value)
                _SCORE_CACHE.move_to_end(keys[index])
            while len(_SCORE_CACHE) > _SCORE_CACHE_ENTRIES:
                _SCORE_CACHE.popitem(last=False)
    return [value for value in scores if value is not None]


def progressive_rerank_candidates(documents: list[Document], limit: int) -> list[Document]:
    """Narrow with cheap signals while retaining anchors and family balance.

    Corpus growth must not let one source type consume the finite cross-encoder
    window. Exact/canonical anchors remain protected; ordinary query-ranked
    candidates compete inside dynamically discovered source-family windows.
    """

    if limit <= 0 or len(documents) <= limit:
        return list(documents)

    def score(item: tuple[int, Document]) -> tuple[float, ...]:
        index, document = item
        metadata = document.metadata
        primary_rank = int(metadata.get("primary_query_rank") or 0)
        query_rank = min(
            (int(value) for value in (metadata.get("query_candidate_ranks") or {}).values()),
            default=0,
        )
        source_rank = int(metadata.get("source_dense_rank") or 0)
        # Source-local ranks are only comparable *inside* one source. Treat all
        # of those bounded candidates as query-responsive peers and let their
        # semantic score order them globally; otherwise every rank-one section
        # from seven sources crowds out a strongly relevant rank-three section.
        retrieval_rank = primary_rank or query_rank or (1 if source_rank else 0)
        return (
            1.0
            if metadata.get("identifier_anchor") or metadata.get("canonical_route_candidate")
            else 0.0,
            1.0 if retrieval_rank else 0.0,
            float(-retrieval_rank) if retrieval_rank else float("-inf"),
            float(metadata.get("retrieval_fused_score", 0.0) or 0.0),
            float(metadata.get("fusion_score", 0.0) or 0.0),
            float(metadata.get("lexical_score", 0.0) or 0.0),
            float(metadata.get("score", 0.0) or 0.0),
            float(-index),
        )

    # Vector stores do not promise a stable order for equal-distance records.
    # Establish an identity order before applying the stable score sort so tied
    # candidates cannot change the eventual prompt between identical requests.
    identity_ordered = sorted(
        documents,
        key=lambda document: str(
            document.metadata.get("chunk_id")
            or document.metadata.get("source_id")
            or document.id
            or document.page_content
        ),
    )
    ranked = [
        document for _, document in sorted(enumerate(identity_ordered), key=score, reverse=True)
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
            "canonical_route_candidate"
        ):
            add(document)

    family_sources: dict[str, dict[str, list[Document]]] = {}
    for document in ranked:
        source_type = str(document.metadata.get("source_type") or "UNKNOWN").upper()
        source_identity = str(
            document.metadata.get("source_id")
            or document.metadata.get("reference")
            or document.metadata.get("parent_id")
            or document.metadata.get("chunk_id")
            or document.id
            or document.page_content
        )
        family_sources.setdefault(source_type, {}).setdefault(source_identity, []).append(document)

    # Diversify within a family too, while keeping a two-chunk section burst.
    # A strict one-per-source round robin separated adjacent chunks from the
    # same relevant page/file until after the finite cross-encoder window; no
    # diversity allowed one large source to monopolize it. Two preserves local
    # section continuity while still advancing to independent sources quickly.
    families: dict[str, list[Document]] = {}
    for family, sources in family_sources.items():
        diversified: list[Document] = []
        depth = 0
        source_burst = 2
        while True:
            added = False
            for source_documents in sources.values():
                window = source_documents[depth : depth + source_burst]
                if window:
                    diversified.extend(window)
                    added = True
            if not added:
                break
            depth += source_burst
        families[family] = diversified

    family_order = sorted(
        families,
        key=lambda family: score((0, families[family][0])),
        reverse=True,
    )

    # A globally fused list can push even the best dense result from a smaller
    # family beyond the cross-encoder window. Reserve only the rank-one leader
    # from each retrieval channel/family. Broader family-rank priority is
    # intentionally avoided because it can overwhelm exact structured matches.
    for family in family_order:
        for rank_field in ("dense_family_rank", "lexical_family_rank"):
            leader = min(
                (
                    document
                    for document in families[family]
                    if int(document.metadata.get(rank_field) or 0) > 0
                ),
                key=lambda document: int(document.metadata.get(rank_field) or 0),
                default=None,
            )
            if leader is not None and int(leader.metadata.get(rank_field) or 0) == 1:
                add(leader)

    # Preserve the strongest original/planned-query candidate in every family,
    # rather than treating every member of a large family's query result as an
    # unlimited reservation.
    for family in family_order:
        protected = next(
            (
                document
                for document in families[family]
                if document.metadata.get("primary_query_rank")
                or document.metadata.get("query_candidate_ranks")
            ),
            None,
        )
        if protected is not None:
            add(protected)

    # Guarantee a modest floor rather than equal shares. The remaining slots
    # stay relevance-driven, so a code question can remain code-heavy while a
    # newly enlarged CODE corpus cannot erase PAGE/ISSUE/ATTACHMENT entirely.
    family_floor = max(1, limit // (len(families) + 1))
    for family in family_order:
        for document in families[family][:family_floor]:
            add(document)

    for document in ranked:
        add(document)

    return selected


def source_balanced_rerank_window(
    documents: list[Document], configured_limit: int
) -> list[Document]:
    """Score the bounded expansion instead of truncating it back out.

    Source-local candidates exist because a compound source's relevant section
    fell outside global top-k. Applying the old fixed-width cheap truncation to
    that expanded pool would recreate the displacement before the cross-encoder
    can compare relevance. Upstream still caps the pool at ``max_candidates``;
    final evidence width and all relevance thresholds remain unchanged.
    """

    if any(document.metadata.get("source_dense_rank") for document in documents):
        return progressive_rerank_candidates(documents, len(documents))
    return progressive_rerank_candidates(documents, configured_limit)


def _structural_section(document: Document) -> str:
    """Return the most specific stable section identity available for evidence."""

    path = document.metadata.get("structure_path")
    if isinstance(path, (list, tuple)):
        return " / ".join(str(value).strip() for value in path if str(value).strip())
    if isinstance(path, str) and path.strip():
        return path.strip()
    return str(document.metadata.get("structure_leaf") or "").strip()


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
        cross_language_score_threshold: float | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        max_length: int = 1024,
        linearize_table_evidence: bool = True,
    ) -> None:
        self._linearize_table_evidence = linearize_table_evidence
        self._model_ref = model_path or model
        self._device = device
        self._revision = revision
        self._batch_size = batch_size
        self._max_length = max_length
        self._top_n = top_n
        self._threshold = score_threshold
        self._exact_code_threshold = exact_code_score_threshold
        self._exact_code_retrieval_floor = exact_code_retrieval_score_floor
        self._cross_language_threshold = cross_language_score_threshold
        self._max_chunks_per_source = max_chunks_per_source
        self.last_retry_count = 0
        self.last_capped_by_source_limit = 0
        self.last_source_cap_bypassed = False
        self.last_threshold_bypassed = False
        self.last_cross_language_documents = 0

    async def rerank(
        self,
        query: str,
        documents: list[Document],
        *,
        score_threshold: float | None = None,
        top_n: int | None = None,
        max_chunks_per_source: int | None = None,
        query_language: str = "",
        allow_threshold_bypass: bool = False,
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
        self.last_threshold_bypassed = False
        self.last_cross_language_documents = 0
        scores = await asyncio.to_thread(self._predict, query, documents)
        scored: list[tuple[float, Document, str]] = []
        all_scored: list[tuple[float, Document, str]] = []
        for document, raw_score in zip(documents, scores, strict=True):
            score = normalized_relevance_score(float(raw_score))
            exact_code_match = (
                score >= self._exact_code_threshold
                and float(document.metadata.get("score") or 0) >= self._exact_code_retrieval_floor
                and _exact_code_anchor_match(query, document)
            )
            source_id = str(
                document.metadata.get("source_id")
                or document.metadata.get("reference")
                or document.metadata.get("chunk_id")
            )
            all_scored.append((score, document, source_id))
            applied = threshold
            if _is_cross_language(query_language, document):
                # A cross-encoder scores a query against evidence in another
                # language systematically lower than a same-language pair, so one
                # absolute floor admits far less evidence for a Spanish question
                # than for the identical English one. Grounding already carries a
                # cross-language allowance for the same reason.
                self.last_cross_language_documents += 1
                if self._cross_language_threshold is not None:
                    applied = min(threshold, self._cross_language_threshold)
            if score < applied and not exact_code_match:
                continue
            scored.append((score, document, source_id))
        if allow_threshold_bypass and not scored and all_scored:
            # Opt-in, and only for routes whose question is broad by nature. A
            # cross-encoder scores a maximally generic query ("what is this
            # project about") low against every passage, so an absolute floor
            # emptied a pool that did contain the overview pages -- 43
            # candidates in, zero out. Everywhere else an empty result is a
            # deliberate refusal and must stay one.
            self.last_threshold_bypassed = True
            scored = sorted(all_scored, key=lambda item: (-item[0], item[2]))[:result_limit]

        ranked: list[Document] = []
        source_counts: dict[str, int] = {}
        ordered_scored = sorted(
            scored,
            key=lambda item: (
                -item[0],
                item[2],
                str(item[1].metadata.get("chunk_id") or item[1].id or ""),
            ),
        )
        for score, document, source_id in ordered_scored:
            if source_counts.get(source_id, 0) >= source_limit:
                self.last_capped_by_source_limit += 1
                continue
            source_counts[source_id] = source_counts.get(source_id, 0) + 1
            document.metadata["rerank_score"] = score
            ranked.append(document)
            if len(ranked) >= result_limit:
                break
        if scored and len(ranked) < result_limit:
            # A source cap is a diversity guard, not a reason to return an
            # unnecessarily short result window. Large pages commonly contain
            # several independently addressable sections; dropping every
            # section after the first `source_limit` chunks made corpus growth
            # suppress relevant evidence even though it had passed the
            # unchanged rerank threshold. Fill only otherwise-empty slots, first
            # from missing source families and then from previously unseen
            # structural sections. Existing ranked evidence is never displaced.
            ranked_ids = {
                str(document.metadata.get("chunk_id") or document.id or document.page_content)
                for document in ranked
            }
            represented_families = {
                str(document.metadata.get("source_type") or "UNKNOWN").upper()
                for document in ranked
            }
            represented_sections = {
                (
                    str(
                        document.metadata.get("source_id")
                        or document.metadata.get("reference")
                        or document.metadata.get("chunk_id")
                    ),
                    _structural_section(document),
                )
                for document in ranked
                if _structural_section(document)
            }

            def backfill(score: float, document: Document, source_id: str) -> None:
                identity = str(
                    document.metadata.get("chunk_id") or document.id or document.page_content
                )
                if identity in ranked_ids or len(ranked) >= result_limit:
                    return
                if source_counts.get(source_id, 0) >= source_limit:
                    self.last_source_cap_bypassed = True
                source_counts[source_id] = source_counts.get(source_id, 0) + 1
                document.metadata["rerank_score"] = score
                ranked.append(document)
                ranked_ids.add(identity)
                represented_families.add(
                    str(document.metadata.get("source_type") or "UNKNOWN").upper()
                )
                section = _structural_section(document)
                if section:
                    represented_sections.add((source_id, section))

            for score, document, source_id in ordered_scored:
                family = str(document.metadata.get("source_type") or "UNKNOWN").upper()
                if family not in represented_families:
                    backfill(score, document, source_id)

            for score, document, source_id in ordered_scored:
                section = _structural_section(document)
                if section and (source_id, section) not in represented_sections:
                    backfill(score, document, source_id)
        return ranked

    def _predict(self, query: str, documents: list[Document]):
        pairs = [
            (
                query,
                document_scoring_evidence(
                    document,
                    linearize_tables_enabled=self._linearize_table_evidence,
                ),
            )
            for document in documents
        ]
        return cached_scores(
            self._model_ref,
            self._max_length,
            pairs,
            lambda uncached: predict_local_scores(
                self._model_ref,
                device=self._device,
                revision=self._revision,
                pairs=uncached,
                batch_size=self._batch_size,
                max_length=self._max_length,
            ),
        )


class RemoteMultilingualReranker(LocalMultilingualReranker):
    """Run identical cross-encoder pairs on the authenticated macOS worker."""

    def __init__(
        self,
        *args,
        base_url: str,
        api_key: str,
        timeout_seconds: float,
        attempts: int = 1,
        max_concurrency: int = 1,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self._base_url = base_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._attempts = attempts
        self._max_concurrency = max_concurrency

    def _predict(self, query: str, documents: list[Document]):
        pairs = [
            (
                query,
                document_scoring_evidence(
                    document,
                    linearize_tables_enabled=self._linearize_table_evidence,
                ),
            )
            for document in documents
        ]
        scores = cached_scores(
            self._model_ref,
            self._max_length,
            pairs,
            lambda uncached: accelerator_scores(
                self._base_url,
                uncached,
                api_key=self._api_key,
                timeout_seconds=self._timeout_seconds,
                max_length=self._max_length,
                attempts=self._attempts,
                max_concurrency=self._max_concurrency,
            ),
        )
        if len(scores) != len(documents):
            raise RuntimeError("Local accelerator returned invalid reranker scores.")
        return scores


_LANGUAGES = {"en", "es"}


def _is_cross_language(query_language: str, document: Document) -> bool:
    """True only when both sides name a language and they differ."""

    question = str(query_language or "").casefold()
    evidence = str(document.metadata.get("language") or "").casefold()
    return question in _LANGUAGES and evidence in _LANGUAGES and question != evidence


def build_reranker(settings: Settings) -> LocalMultilingualReranker:
    if settings.local_accelerator_url:
        return RemoteMultilingualReranker(
            settings.local_rerank_model,
            device=settings.local_rerank_device,
            model_path=settings.local_models_path,
            revision=settings.local_rerank_revision,
            top_n=settings.rerank_top_n,
            score_threshold=settings.rerank_score_threshold,
            exact_code_score_threshold=settings.exact_code_rerank_score_threshold,
            exact_code_retrieval_score_floor=settings.exact_code_retrieval_score_floor,
            cross_language_score_threshold=settings.rerank_cross_language_score_threshold,
            max_chunks_per_source=settings.max_chunks_per_source,
            batch_size=settings.local_rerank_batch_size,
            max_length=settings.local_rerank_max_length,
            linearize_table_evidence=settings.linearize_table_evidence,
            base_url=settings.local_accelerator_url,
            api_key=settings.internal_api_key,
            timeout_seconds=settings.local_accelerator_timeout_seconds,
            attempts=settings.local_accelerator_retry_attempts,
            max_concurrency=settings.accelerator_max_concurrency,
        )
    return LocalMultilingualReranker(
        settings.local_rerank_model,
        device=settings.local_rerank_device,
        model_path=settings.local_models_path,
        revision=settings.local_rerank_revision,
        top_n=settings.rerank_top_n,
        score_threshold=settings.rerank_score_threshold,
        exact_code_score_threshold=settings.exact_code_rerank_score_threshold,
        exact_code_retrieval_score_floor=settings.exact_code_retrieval_score_floor,
        cross_language_score_threshold=settings.rerank_cross_language_score_threshold,
        max_chunks_per_source=settings.max_chunks_per_source,
        batch_size=settings.local_rerank_batch_size,
        max_length=settings.local_rerank_max_length,
        linearize_table_evidence=settings.linearize_table_evidence,
    )


def _load_local_model(model_ref: str, device: str, revision: str, max_length: int):
    expanded = Path(model_ref).expanduser()
    resolved = str(expanded) if expanded.exists() else model_ref
    key = (resolved + "@" + revision + f"#max_length={max_length}", device)
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
            max_length=max_length,
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
    max_length: int = 1024,
):
    """Score text pairs with the pinned local cross-encoder and shared inference lock.

    The batch size matters more than it looks. A candidate pool of 50 at batch 8 is
    seven sequential MPS round trips; the GPU is idle between them, so a larger
    batch is close to free until memory binds.
    """

    if not pairs:
        return []
    model = _load_local_model(model_ref, device, revision, max_length)
    with _LOCAL_INFERENCE_LOCK:
        effective_batch_size = min(batch_size, len(pairs))
        try:
            scores = model.predict(
                pairs,
                batch_size=effective_batch_size,
                show_progress_bar=False,
                activation_fn=_identity_activation(),
            )
        except RuntimeError as failure:
            # Metal can retain allocations owned by other local models even
            # after our normal per-call cache release. Recover once with a
            # smaller bounded batch; an unrelated runtime error, or a second
            # allocation failure, remains visible to the caller.
            if not _is_mps_out_of_memory(failure, device) or effective_batch_size <= 1:
                raise
            _release_mps_cache()
            scores = model.predict(
                pairs,
                batch_size=max(1, effective_batch_size // 2),
                show_progress_bar=False,
                activation_fn=_identity_activation(),
            )
        if device.casefold().startswith("mps"):
            # SentenceTransformers returns CPU-backed scores. Release cached
            # Metal allocations between long evaluation cases so a complete
            # suite cannot accumulate allocator state until it OOMs.
            _release_mps_cache()
        return scores


def _is_mps_out_of_memory(failure: RuntimeError, device: str) -> bool:
    return (
        device.casefold().startswith("mps")
        and "mps backend out of memory" in str(failure).casefold()
    )


def _release_mps_cache() -> None:
    import gc
    import torch

    torch.mps.synchronize()
    gc.collect()
    torch.mps.empty_cache()


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
    return "".join(character for character in value if character in "\n\t" or ord(character) >= 32)[
        :16000
    ]


def scoring_evidence(value: str, *, linearize_tables_enabled: bool = True) -> str:
    """Evidence prepared for the cross-encoder rather than for the generator.

    The generator sees the original Markdown so it can reproduce a table. The
    cross-encoder was trained on running text and cannot recover a cell's meaning
    from its column position, so it sees one sentence per row instead.
    """

    cleaned = sanitize_evidence(value)
    if not linearize_tables_enabled:
        return cleaned
    # Re-apply the bound after linearisation. Repeating a header on every row
    # grows the text, so sizing only the input leaves the output unbounded.
    return sanitize_evidence(linearize_tables(cleaned))


def document_scoring_evidence(document: Document, *, linearize_tables_enabled: bool = True) -> str:
    """Add authoritative document context to the passage scored by the reranker.

    Structured chunks intentionally keep headings in metadata so the body is not
    repeated in every window.  Scoring only ``page_content`` discarded those
    headings and made equivalent reindexes sensitive to HNSW tie ordering among
    similar chunks.  Title and section path are source data, not query-derived
    hints, and make the cross-encoder comparison stable across regenerated IDs.
    """

    title = str(document.metadata.get("title") or "").strip()
    raw_path = document.metadata.get("structure_path")
    path_values: list[str] = []
    if isinstance(raw_path, (list, tuple)):
        path_values = [str(value).strip() for value in raw_path if str(value).strip()]
    elif isinstance(raw_path, str) and raw_path.strip():
        try:
            decoded = json.loads(raw_path)
        except json.JSONDecodeError:
            decoded = raw_path
        if isinstance(decoded, list):
            path_values = [str(value).strip() for value in decoded if str(value).strip()]
        else:
            path_values = [str(decoded).strip()]

    context: list[str] = []
    if title:
        context.append(f"Title: {title}")
    section = " > ".join(value for value in path_values if value != title)
    if section:
        context.append(f"Section: {section}")
    body = scoring_evidence(
        document.page_content,
        linearize_tables_enabled=linearize_tables_enabled,
    )
    return sanitize_evidence("\n".join((*context, body)))


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
