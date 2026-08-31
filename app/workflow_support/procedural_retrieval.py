"""Generic multi-source retrieval support for procedural questions."""

from __future__ import annotations

import math
import re
from typing import Any

from langchain_core.documents import Document


_PROCEDURAL_PATTERNS = (
    re.compile(r"\bhow\s+(?:do|can|should|would)\s+(?:i|we|a user)\b", re.IGNORECASE),
    re.compile(r"\bhow\s+to\b", re.IGNORECASE),
    re.compile(r"\b(?:steps?|procedure|workflow|walkthrough|instructions?)\b", re.IGNORECASE),
    re.compile(r"\b(?:log[ -]?in|sign[ -]?in|authenticate)\b", re.IGNORECASE),
)


def is_procedural_question(question: str) -> bool:
    return any(pattern.search(question) for pattern in _PROCEDURAL_PATTERNS)


def procedural_rerank_query(question: str) -> str:
    """Add intent aliases for ranking without changing the user's question."""

    aliases = "procedure workflow steps implementation configuration navigation validation failure handling"
    if re.search(r"\b(?:log[ -]?in|sign[ -]?in|authenticate)\b", question, re.IGNORECASE):
        aliases += " authentication credentials login screen session access"
    return f"{question.strip()}\nRelevant concepts: {aliases}"


def _source_family(document: Document) -> str:
    metadata = document.metadata
    return str(
        metadata.get("source_type")
        or metadata.get("provider")
        or metadata.get("content_type")
        or "UNKNOWN"
    ).strip().upper()


def _cheap_score(document: Document) -> tuple[float, ...]:
    metadata = document.metadata
    return (
        1.0 if metadata.get("identifier_anchor") else 0.0,
        float(metadata.get("retrieval_fused_score", 0.0) or 0.0),
        float(metadata.get("fusion_score", 0.0) or 0.0),
        float(metadata.get("lexical_score", 0.0) or 0.0),
        float(metadata.get("score", 0.0) or 0.0),
    )


def balanced_source_candidate_pool(
    documents: list[Document], limit: int
) -> list[Document]:
    """Narrow without allowing one current or future source type to dominate."""

    if limit <= 0 or len(documents) <= limit:
        return list(documents)
    families: dict[str, list[Document]] = {}
    for document in documents:
        families.setdefault(_source_family(document), []).append(document)
    for family_documents in families.values():
        family_documents.sort(key=_cheap_score, reverse=True)

    ordered_families = sorted(
        families,
        key=lambda family: _cheap_score(families[family][0]),
        reverse=True,
    )
    selected: list[Document] = []
    depth = 0
    while len(selected) < limit:
        added = False
        for family in ordered_families:
            family_documents = families[family]
            if depth < len(family_documents):
                selected.append(family_documents[depth])
                added = True
                if len(selected) == limit:
                    break
        if not added:
            break
        depth += 1
    return selected


async def rerank_source_families(
    reranker: Any,
    query: str,
    documents: list[Document],
    *,
    top_n: int,
) -> list[Document]:
    """Rerank each source family independently, then merge by ranked depth."""

    if not documents:
        return []
    families: dict[str, list[Document]] = {}
    for document in documents:
        families.setdefault(_source_family(document), []).append(document)

    family_limit = max(1, math.ceil(top_n / max(1, len(families))))
    ranked_families: dict[str, list[Document]] = {}
    enriched_query = procedural_rerank_query(query)
    for family, family_documents in families.items():
        try:
            ranked = await reranker.rerank(
                enriched_query,
                family_documents,
                score_threshold=0.0,
                top_n=min(len(family_documents), max(family_limit, 2)),
            )
        except TypeError as error:
            if "top_n" not in str(error) and "score_threshold" not in str(error):
                raise
            ranked = await reranker.rerank(enriched_query, family_documents)
        ranked_families[family] = ranked or family_documents[:family_limit]

    family_order = sorted(
        ranked_families,
        key=lambda family: float(
            ranked_families[family][0].metadata.get("rerank_score", 0.0) or 0.0
        )
        if ranked_families[family]
        else 0.0,
        reverse=True,
    )
    merged: list[Document] = []
    depth = 0
    while len(merged) < top_n:
        added = False
        for family in family_order:
            ranked = ranked_families[family]
            if depth < len(ranked):
                ranked[depth].metadata["procedural_source_family"] = family
                merged.append(ranked[depth])
                added = True
                if len(merged) == top_n:
                    break
        if not added:
            break
        depth += 1
    return merged
