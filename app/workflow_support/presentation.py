from __future__ import annotations

import re
from collections.abc import AsyncIterator

from langchain_core.documents import Document

from app.llm import GroundedAnswer
from app.grounding import _material_claims


def _highest_rerank_score(documents: list[Document]) -> float:
    """Ignore context neighbours whose score was never cross-encoded."""

    return max(
        (
            float(document.metadata["rerank_score"])
            for document in documents
            if "rerank_score" in document.metadata
        ),
        default=0.0,
    )


async def _incrementally_verified_events(
    verifier: object,
    *,
    question: str,
    documents: list[Document],
    generated: GroundedAnswer,
    language: str,
) -> AsyncIterator[dict[str, object]]:
    """Release only sentences that independently pass the grounding verifier."""

    for index, sentence in enumerate(_material_claims(generated.answer), start=1):
        citations = [
            int(value) for value in re.findall(r"\[SOURCE (\d+)\]", sentence)
        ]
        verdict = await verifier.verify(
            question,
            documents,
            GroundedAnswer(answer=sentence, citations=citations),
            answer_language=language,
        )
        if verdict.supported:
            clean = re.sub(r"\s*\[SOURCE \d+\]", "", sentence).strip()
            yield {
                "type": "answer_delta",
                "delta": clean + " ",
                "verification": "verified",
            }
        else:
            yield {
                "type": "answer_sentence_rejected",
                "claimIndex": index,
                "reason": verdict.reason_code,
            }

def _expand_candidate_neighbors(
    ranked: list[Document],
    candidates: list[Document],
    *,
    top_n: int,
    max_per_anchor: int,
    max_per_source: int,
) -> list[Document]:
    if max_per_anchor <= 0:
        return ranked[:top_n]
    selected: list[Document] = []
    selected_ids: set[str] = set()
    source_counts: dict[str, int] = {}

    def add(document: Document) -> bool:
        identity = str(document.metadata.get("chunk_id") or id(document))
        source_id = str(document.metadata.get("source_id") or document.metadata.get("reference") or identity)
        if identity in selected_ids or source_counts.get(source_id, 0) >= max_per_source:
            return False
        selected_ids.add(identity)
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        selected.append(document)
        return True

    for anchor in ranked:
        if len(selected) >= top_n:
            break
        add(anchor)
        parent = str(anchor.metadata.get("parent_id") or anchor.metadata.get("source_id") or "")
        ordinal = int(anchor.metadata.get("chunk_ordinal") or 0)
        source_version = str(anchor.metadata.get("source_version") or "")
        neighbors = sorted(
            (
                candidate
                for candidate in candidates
                if str(candidate.metadata.get("parent_id") or candidate.metadata.get("source_id") or "") == parent
                and str(candidate.metadata.get("source_version") or "") == source_version
                and abs(int(candidate.metadata.get("chunk_ordinal") or 0) - ordinal) == 1
            ),
            key=lambda item: abs(int(item.metadata.get("chunk_ordinal") or 0) - ordinal),
        )
        added = 0
        for neighbor in neighbors:
            if len(selected) >= top_n or added >= max_per_anchor:
                break
            if add(neighbor):
                neighbor.metadata["context_neighbor"] = True
                neighbor.metadata["neighbor_of"] = str(
                    anchor.metadata.get("chunk_id") or anchor.metadata.get("source_id") or ""
                )
                neighbor.metadata["inherited_score"] = float(
                    anchor.metadata.get("rerank_score", 0)
                )
                neighbor.metadata.pop("rerank_score", None)
                added += 1
    for document in ranked:
        if len(selected) >= top_n:
            break
        add(document)
    return selected


def _stream_progress(
    node_name: str, language: str, details: dict[str, object] | None = None
) -> dict[str, object] | None:
    """Map internal graph nodes to content-free, user-facing progress events."""

    stage_by_node = {
        "plan_queries": "planning",
        "retrieve": "retrieving",
        "feature_affinity": "retrieving",
        "rerank": "ranking",
        "validate_evidence_completeness": "checking_evidence",
        "recover_query": "refining_search",
        "generate": "writing",
        "validate_citations": "checking_answer",
        "validate_completeness": "checking_answer",
        "repair_completeness": "refining_search",
        "verify_grounding": "checking_answer",
    }
    stage = stage_by_node.get(node_name)
    if stage is None:
        return None
    messages = {
        "en": {
            "planning": "Understanding your question…",
            "retrieving": "Searching the project knowledge…",
            "ranking": "Selecting the strongest evidence…",
            "checking_evidence": "Checking evidence coverage…",
            "refining_search": "Refining the search…",
            "writing": "Preparing a grounded answer…",
            "checking_answer": "Verifying the answer…",
        },
        "es": {
            "planning": "Entendiendo tu pregunta…",
            "retrieving": "Buscando en el conocimiento del proyecto…",
            "ranking": "Seleccionando la evidencia más sólida…",
            "checking_evidence": "Comprobando la cobertura de la evidencia…",
            "refining_search": "Mejorando la búsqueda…",
            "writing": "Preparando una respuesta fundamentada…",
            "checking_answer": "Verificando la respuesta…",
        },
    }
    localized = messages["es" if language == "es" else "en"]
    message = localized[stage]
    if details is not None and language != "es":
        if node_name == "retrieve" and isinstance(details.get("candidates"), list):
            message = f"Found {len(details['candidates'])} candidates; preparing ranking…"
        elif node_name == "rerank" and isinstance(details.get("documents"), list):
            message = f"Selected {len(details['documents'])} evidence passages; checking coverage…"
        elif node_name == "verify_grounding":
            generated = details.get("generated")
            answer = str(getattr(generated, "answer", ""))
            claim_count = len(_material_claims(answer)) if answer else 0
            if claim_count:
                message = f"Verifying {claim_count} claims…"
    return {"type": "status", "stage": stage, "message": message}


def _answer_deltas(answer: str, target_characters: int = 32) -> list[str]:
    """Split verified Markdown into readable deltas without breaking words."""

    if not answer:
        return []
    deltas: list[str] = []
    cursor = 0
    while cursor < len(answer):
        boundary = min(cursor + target_characters, len(answer))
        if boundary < len(answer):
            next_space = answer.find(" ", boundary)
            next_newline = answer.find("\n", boundary)
            candidates = [value for value in (next_space, next_newline) if value >= 0]
            if candidates:
                boundary = min(candidates) + 1
        deltas.append(answer[cursor:boundary])
        cursor = boundary
    return deltas
