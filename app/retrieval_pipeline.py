"""Provider-independent retrieval decisions used after authorized search.

The Chroma adapter remains the dense retriever.  These small interfaces keep
lexical scoring, fusion, authorization validation, and context evaluation
replaceable without coupling them to an LLM or vector vendor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Protocol, Sequence

from langchain_core.documents import Document
from app.lexical_tokens import tokens as lexical_tokens


class SparseRetriever(Protocol):
    def rank(self, query: str, documents: Sequence[Document]) -> list[Document]: ...


class CandidateFusion(Protocol):
    def fuse(
        self,
        lexical: Sequence[Document],
        dense: Sequence[Document],
        *,
        limit: int,
    ) -> list[Document]: ...


class ContextEvaluator(Protocol):
    def evaluate(self, question: str, documents: Sequence[Document]) -> "ContextQuality": ...


def deduplicate_candidate_bodies(documents: Sequence[Document]) -> list[Document]:
    """Keep the best-ranked copy of equivalent evidence before reranking."""

    unique: list[Document] = []
    by_body: dict[str, Document] = {}
    for document in documents:
        identity = str(document.metadata.get("content_hash") or "").strip()
        if not identity:
            identity = " ".join(document.page_content.split()).casefold()
        existing = by_body.get(identity)
        if existing is None:
            by_body[identity] = document
            unique.append(document)
            continue
        references = existing.metadata.setdefault("duplicate_references", [])
        reference = str(
            document.metadata.get("reference")
            or document.metadata.get("source_id")
            or document.metadata.get("chunk_id")
            or ""
        )
        if reference and reference not in references:
            references.append(reference)
    return unique


def _tokens(value: str) -> list[str]:
    # Whole tokens plus identifier subwords: see app/lexical_tokens for why an
    # treating a compound event identifier as one atomic token made the lexical
    # channel worse than useless
    # on exactly the questions it should have been best at.
    return lexical_tokens(value)


class BM25Retriever:
    """Small deterministic BM25 scorer over authorized candidate text.

    The class is deliberately corpus-agnostic: production adapters can provide
    a native sparse index later, while tests and local deployments can score an
    authorized candidate window without another service.
    """

    def __init__(self, *, k1: float = 1.2, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def rank(self, query: str, documents: Sequence[Document]) -> list[Document]:
        if not documents:
            return []
        query_terms = set(_tokens(query))
        tokenized = [_tokens(document.page_content + " " + self._metadata(document)) for document in documents]
        document_frequency: dict[str, int] = {}
        for values in tokenized:
            for term in set(values):
                document_frequency[term] = document_frequency.get(term, 0) + 1
        average_length = sum(map(len, tokenized)) / max(len(tokenized), 1)
        scored: list[tuple[float, int, Document]] = []
        for index, (document, values) in enumerate(zip(documents, tokenized, strict=True)):
            frequencies: dict[str, int] = {}
            for term in values:
                frequencies[term] = frequencies.get(term, 0) + 1
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = document_frequency.get(term, 0)
                idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
                length_norm = 1 - self.b + self.b * len(values) / max(average_length, 1)
                score += idf * (frequency * (self.k1 + 1)) / (frequency + self.k1 * length_norm)
            document.metadata["lexical_score"] = score
            scored.append((score, -index, document))
        return [document for _score, _index, document in sorted(scored, key=lambda item: (item[0], item[1]), reverse=True)]

    @staticmethod
    def _metadata(document: Document) -> str:
        """Return searchable metadata with deterministic field boosts.

        Code and work-item questions are often answered by an exact path,
        symbol, issue key, or document title even when the surrounding prose
        is semantically similar to many other chunks.  Repeating metadata
        terms here is a small BM25 field boost (not a sentence or product
        special-case) and mirrors the field-aware weighting used by mature
        hybrid search systems.
        """

        fields = (
            ("title", 2),
            ("path", 3),
            ("symbol", 4),
            ("reference", 3),
            ("issue_key", 4),
            ("locator", 2),
            ("important_kwd", 5),
            ("keywords", 3),
            ("question_terms", 3),
        )
        values: list[str] = []
        for key, weight in fields:
            value = document.metadata.get(key)
            if isinstance(value, (list, tuple, set)):
                text = " ".join(str(item) for item in value)
            else:
                text = str(value or "")
            if text:
                values.extend([text] * weight)
        return " ".join(values)


class ReciprocalRankFusion:
    """Deterministic RRF with exact lexical score retained for observability."""

    def __init__(
        self,
        *,
        k: int = 60,
        lexical_weight: float = 1.0,
        dense_weight: float = 1.0,
    ) -> None:
        self.k = max(1, k)
        if lexical_weight <= 0 or dense_weight <= 0:
            raise ValueError("Fusion weights must be greater than zero")
        self.lexical_weight = lexical_weight
        self.dense_weight = dense_weight

    def fuse(
        self,
        lexical: Sequence[Document],
        dense: Sequence[Document],
        *,
        limit: int,
    ) -> list[Document]:
        by_identity: dict[str, Document] = {}
        scores: dict[str, float] = {}
        for weight, ranked in (
            (self.lexical_weight, lexical),
            (self.dense_weight, dense),
        ):
            for rank, document in enumerate(ranked, start=1):
                identity = _identity(document)
                existing = by_identity.setdefault(identity, document)
                if existing is not document and document.metadata.get(
                    "identifier_anchor"
                ):
                    # The lexical channel is fused first. When an exact-match
                    # document is also present there, retaining only that first
                    # clone silently discarded the anchor marker from the dense
                    # exact-lookup channel and triggered an unnecessary repair.
                    existing.metadata["identifier_anchor"] = True
                    existing.metadata["identifier_anchor_score"] = max(
                        float(
                            existing.metadata.get("identifier_anchor_score") or 0
                        ),
                        float(document.metadata.get("identifier_anchor_score") or 0),
                    )
                scores[identity] = scores.get(identity, 0.0) + weight / (self.k + rank)
        ordered = sorted(
            by_identity.values(),
            key=lambda document: (
                scores[_identity(document)],
                float(document.metadata.get("lexical_score") or 0),
                float(document.metadata.get("score") or 0),
            ),
            reverse=True,
        )[: max(0, limit)]
        for document in ordered:
            document.metadata["fusion_score"] = scores[_identity(document)]
            document.metadata["retrieval_channel"] = "hybrid"
        return ordered


def _identity(document: Document) -> str:
    return str(document.metadata.get("chunk_id") or document.metadata.get("reference") or id(document))


@dataclass(frozen=True)
class ContextQuality:
    quality: str
    relevance: float
    completeness: float
    missing_information: tuple[str, ...] = field(default_factory=tuple)
    retry_recommended: bool = False
    failure_reason: str = ""


class HeuristicContextEvaluator:
    """Cheap pre-generation gate; semantic verification remains downstream."""

    def evaluate(self, question: str, documents: Sequence[Document]) -> ContextQuality:
        if not documents:
            return ContextQuality("INSUFFICIENT", 0.0, 0.0, ("relevant evidence",), True, "NO_RESULTS")
        relevance = max(
            float(document.metadata.get("rerank_score") or document.metadata.get("score") or 0)
            for document in documents
        )
        exact = max((float(document.metadata.get("lexical_score") or 0) for document in documents), default=0.0)
        completeness = min(1.0, len(documents) / 2 + min(exact / 4, 0.5))
        sufficient = relevance >= 0.25 or exact > 0
        return ContextQuality(
            "SUFFICIENT" if sufficient else "INSUFFICIENT",
            round(min(relevance, 1.0), 3),
            round(completeness, 3),
            () if sufficient else ("more specific supporting evidence",),
            not sufficient,
            "" if sufficient else "LOW_RELEVANCE",
        )


def validate_authorized_candidates(
    documents: Sequence[Document], *, project_id: str, access_policy_ids: Sequence[str]
) -> list[Document]:
    """Fail closed before candidates can enter reranking or LLM context."""

    required_policy = f"project:{project_id}"
    if required_policy not in access_policy_ids:
        raise PermissionError("Authorized project policy is required.")
    return [
        document
        for document in documents
        if document.metadata.get("project_id") in (None, "", project_id)
        and document.metadata.get("access_policy_id") in (None, "", required_policy)
    ]
