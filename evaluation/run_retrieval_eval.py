"""Run the real local retrieval and reranking path against a gold suite."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict, deque
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any

from chromadb import HttpClient
from langchain_core.documents import Document

from app.chroma_collections import project_collection_name, verify_project_collection
from app.config import Settings
from app.embedding import build_embedder
from app.models import RagRequest
from app.reranking import (
    _exact_code_anchor_match,
    build_reranker,
    normalized_relevance_score,
    predict_local_scores,
    progressive_rerank_candidates,
    scoring_evidence,
)
from app.retrieval import ChromaAccessRetriever
from app.workflow import AuthorizedRagWorkflow
from app.workflow_nodes.retrieval import (
    _exact_identifier_tokens,
    _forced_anchor_tokens,
    _prefilter_candidates,
    _retain_explicit_identifier_anchors,
    _source_volume_discounted_score,
)
from app.workflow_support.query_analysis import (
    _exact_term_ratio,
    _exact_terms,
    _source_identity,
)
from app.retrieval_pipeline import (
    BM25Retriever,
    ReciprocalRankFusion,
    deduplicate_candidate_bodies,
)
try:
    from evaluation.phoenix_client import publish_scores_to_phoenix
    from evaluation.score import (
        generation_dashboard_scores,
        generation_dashboard_sample_counts,
        retrieval_dashboard_sample_counts,
        retrieval_dashboard_scores,
        score,
        score_generation,
    )
except ModuleNotFoundError:  # Direct `python evaluation/run_retrieval_eval.py` execution.
    from phoenix_client import publish_scores_to_phoenix
    from score import (
        generation_dashboard_scores,
        generation_dashboard_sample_counts,
        retrieval_dashboard_sample_counts,
        retrieval_dashboard_scores,
        score,
        score_generation,
    )


# entity_key is carried through from ingestion (structured_chunking sets it on
# chunk metadata; vector.py passes non-reserved keys straight into Chroma). A
# registry entry names its event there even when the event is not a section
# heading, so a gold predicate can address it without the manifest having to
# carry chunk text.
_MANIFEST_FIELDS = (
    "structure_path",
    "title",
    "source_id",
    "doc_category",
    "entity_key",
)
# Bumped with the field list. A cached manifest captured under the old schema
# has no entity_key, and reusing it would not fail -- it would silently resolve
# fewer cases, which is exactly the class of error this preflight exists to
# stop.
_MANIFEST_VERSION = 4
_MINIMUM_GOLD_RESOLUTION_RATE = 0.95
_PARAPHRASE_GROUPS_PATH = Path(__file__).with_name("paraphrase_groups.json")
_DEFAULT_SUITES_PATH = Path(__file__).with_name("gold_suites.jsonl")
_BILINGUAL_SUITES_PATH = Path(__file__).with_name("bilingual_gold_suites.jsonl")
_RERANK_SWEEP = (
    ("baseline", 12, 16, 8, 0.10, 3),
    ("regular_candidates_16", 16, 16, 8, 0.10, 3),
    ("inventory_candidates_20", 12, 20, 8, 0.10, 3),
    ("top_n_10", 12, 16, 10, 0.10, 3),
    ("threshold_005", 12, 16, 8, 0.05, 3),
    ("source_cap_4", 12, 16, 8, 0.10, 4),
    ("combined", 16, 20, 10, 0.05, 3),
)


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _apply_reviewed_references(
    cases: list[dict[str, Any]], path: Path, *, expected_dataset_version: str
) -> list[dict[str, Any]]:
    """Join separately reviewed references onto source-bound bilingual cases."""

    references = _load_jsonl(path)
    by_id: dict[str, dict[str, Any]] = {}
    for reference in references:
        case_id = str(reference.get("case_id") or "")
        if not case_id or case_id in by_id:
            raise ValueError(f"Invalid or duplicate reviewed reference case_id: {case_id!r}")
        if reference.get("reference_status") != "reviewed":
            raise ValueError(f"Reference {case_id} is not marked reviewed")
        if not str(reference.get("reference") or "").strip():
            raise ValueError(f"Reference {case_id} has no answer text")
        by_id[case_id] = reference
    versions = {str(reference.get("dataset_version") or "") for reference in references}
    if versions != {expected_dataset_version}:
        raise ValueError(
            "Reviewed reference dataset_version mismatch: "
            f"expected {expected_dataset_version!r}, found {sorted(versions)!r}"
        )
    known = {str(case.get("id")) for case in cases}
    unknown = sorted(by_id.keys() - known)
    if unknown:
        raise ValueError(f"Reviewed references name unknown cases: {unknown[:10]}")
    merged: list[dict[str, Any]] = []
    for case in cases:
        reference = by_id.get(str(case.get("id")))
        if reference is None:
            merged.append(case)
            continue
        if reference.get("query_language") != case.get("query_language"):
            raise ValueError(f"Reference language does not match case {case.get('id')}")
        if reference.get("target_evidence_language") != case.get(
            "target_evidence_language"
        ):
            raise ValueError(
                f"Reference evidence language does not match case {case.get('id')}"
            )
        expected_question_hash = hashlib.sha256(
            str(case.get("question") or "").encode("utf-8")
        ).hexdigest()
        if reference.get("question_sha256") != expected_question_hash:
            raise ValueError(
                f"Reference question_sha256 does not match case {case.get('id')}"
            )
        merged.append(
            {
                **case,
                "reference": reference["reference"],
                "reference_status": "reviewed",
                "dataset_version": expected_dataset_version,
            }
        )
    return merged


def _reviewed_bilingual_ragas_cases(
    cases: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expected = [
        case
        for case in cases
        if case.get("suite") == "bilingual_curated"
        and case.get("answerable") is True
        and case.get("retired") is not True
    ]
    missing = [
        str(case.get("id"))
        for case in expected
        if case.get("reference_status") != "reviewed"
    ]
    if missing:
        raise ValueError(
            "Reviewed bilingual references are incomplete: "
            + ", ".join(missing[:10])
        )
    directions = {
        (case.get("query_language"), case.get("target_evidence_language"))
        for case in expected
    }
    required = {("en", "en"), ("es", "es"), ("en", "es"), ("es", "en")}
    if not required.issubset(directions):
        raise ValueError(
            f"Reviewed bilingual references are missing directions: {sorted(required - directions)}"
        )
    return expected


def retired_cases(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Cases withdrawn from scoring, each carrying the reason it was withdrawn.

    A case whose evidence has left the corpus cannot be scored, and leaving it
    in depresses every metric for a reason unrelated to retrieval quality. It is
    withdrawn rather than deleted so the record of what was dropped, and why,
    stays in the suite -- an unexplained absence is what this preflight exists
    to prevent.
    """

    return [case for case in cases if case.get("retired") is True]


def _load_evaluation_cases(path: Path) -> list[dict[str, Any]]:
    cases = _load_jsonl(path)
    if path.resolve() == _DEFAULT_SUITES_PATH.resolve():
        cases.extend(_load_jsonl(_BILINGUAL_SUITES_PATH))
    missing_reason = sorted(
        str(case.get("id"))
        for case in retired_cases(cases)
        if not str(case.get("retired_reason") or "").strip()
    )
    if missing_reason:
        raise ValueError(
            "Retired evaluation cases must record retired_reason: "
            + ", ".join(missing_reason[:10])
        )
    identifiers = [str(case.get("id")) for case in cases]
    duplicates = sorted(
        identifier for identifier, count in Counter(identifiers).items() if count > 1
    )
    if duplicates:
        raise ValueError(f"Duplicate evaluation case ids: {duplicates[:10]}")
    return cases


def _manifest_cache_path(output: Path) -> Path:
    return output.with_name(f"{output.stem}.manifest.json")


def _namespace_manifest(
    collection: Any,
    *,
    project_id: str,
    logical_collection: str,
    cache_path: Path,
) -> dict[str, dict[str, str]]:
    if cache_path.exists():
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if (
            cached.get("project_id") == project_id
            and cached.get("collection") == logical_collection
            and cached.get("manifest_version") == _MANIFEST_VERSION
            and isinstance(cached.get("chunks"), dict)
        ):
            return cached["chunks"]

    chunks: dict[str, dict[str, str]] = {}
    offset = 0
    page_size = 1_000
    while True:
        page = collection.get(
            where={"project_id": {"$eq": project_id}},
            limit=page_size,
            offset=offset,
            include=["metadatas"],
        )
        identifiers = list(page.get("ids", []))
        metadatas = list(page.get("metadatas", []))
        for chunk_id, metadata in zip(identifiers, metadatas, strict=True):
            values = dict(metadata or {})
            if values.get("record_kind") == "__vocabulary__":
                continue
            canonical_id = str(values.get("canonical_chunk_id") or chunk_id)
            chunks[canonical_id] = {
                field: str(values.get(field) or "") for field in _MANIFEST_FIELDS
            }
        if len(identifiers) < page_size:
            break
        offset += page_size

    cache_path.write_text(
        json.dumps(
            {
                "project_id": project_id,
                "collection": logical_collection,
                "manifest_version": _MANIFEST_VERSION,
                "chunks": chunks,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return chunks


def _gold_ids(
    case: dict[str, Any], manifest: dict[str, dict[str, str]]
) -> list[str]:
    predicates = case.get("gold_match", {}).get("any_of", [])

    def predicate_matches(
        predicate: dict[str, Any], metadata: dict[str, str]
    ) -> bool:
        if "all_of" in predicate:
            return all(
                predicate_matches(item, metadata)
                for item in predicate.get("all_of", [])
            )
        field = str(predicate.get("field") or "")
        actual = str(metadata.get(field) or "").casefold()
        if field not in _MANIFEST_FIELDS:
            return False
        if "equals" in predicate:
            return actual == str(predicate.get("equals") or "").casefold()
        expected = str(predicate.get("contains") or "").casefold()
        if not expected:
            return False
        if expected in actual:
            return True
        # Ingestion formats section paths as JSON strings and some importers
        # omit presentational brackets around stable section identifiers.
        normalized_expected = re.sub(r"[^a-z0-9]+", "", expected)
        normalized_actual = re.sub(r"[^a-z0-9]+", "", actual)
        return bool(normalized_expected) and normalized_expected in normalized_actual

    matches: list[str] = []
    for chunk_id, metadata in manifest.items():
        for predicate in predicates:
            if predicate_matches(predicate, metadata):
                matches.append(chunk_id)
                break
    return matches


def _predicate_values(predicate: dict[str, Any]):
    """Every literal a predicate tries to match, flattening all_of groups."""

    if "all_of" in predicate:
        for item in predicate.get("all_of", []):
            yield from _predicate_values(item)
        return
    value = str(predicate.get("equals") or predicate.get("contains") or "")
    if value:
        yield str(predicate.get("field") or ""), value


def _unresolved_diagnostics(
    unresolved: list[dict[str, Any]], manifest: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """Separate "addressed to the wrong field" from "not in the corpus".

    A failing predicate has two very different causes, and the remedies are
    opposites: repoint the predicate, or retire the case. Reporting only a count
    of unresolved cases leaves that triage to guesswork, which is how a suite
    accumulates cases nobody can act on.
    """

    def normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.casefold())

    # One normalized haystack per field. The separator is a space, which cannot
    # appear in a normalized needle, so nothing matches across two entries.
    haystacks = {
        field: " ".join(normalized(values.get(field, "")) for values in manifest.values())
        for field in _MANIFEST_FIELDS
    }
    diagnostics: dict[str, Any] = {}
    repointable = 0
    for case in unresolved:
        found: dict[str, list[str]] = {}
        values: list[str] = []
        for predicate in case.get("gold_match", {}).get("any_of", []):
            for field, value in _predicate_values(predicate):
                values.append(f"{field}={value}")
                needle = normalized(value)
                if not needle:
                    continue
                for candidate, haystack in haystacks.items():
                    if candidate != field and needle in haystack:
                        found.setdefault(value, []).append(candidate)
        if found:
            repointable += 1
        diagnostics[str(case.get("id"))] = {
            "predicates": values,
            "present_in_other_fields": {
                value: sorted(set(fields)) for value, fields in found.items()
            },
            "verdict": "REPOINTABLE" if found else "ABSENT_FROM_CORPUS",
        }
    return {
        "repointable_cases": repointable,
        "absent_from_corpus_cases": len(unresolved) - repointable,
        "by_case": diagnostics,
    }


def _validate_gold_resolution(
    cases: list[dict[str, Any]],
    manifest: dict[str, dict[str, str]],
    *,
    minimum_rate: float = _MINIMUM_GOLD_RESOLUTION_RATE,
) -> dict[str, Any]:
    withdrawn = retired_cases(cases)
    answerable = [
        case
        for case in cases
        if case.get("answerable") is True and case.get("retired") is not True
    ]
    unresolved_cases = [case for case in answerable if not _gold_ids(case, manifest)]
    unresolved = [str(case.get("id")) for case in unresolved_cases]
    resolved = len(answerable) - len(unresolved)
    rate = resolved / len(answerable) if answerable else 0.0
    diagnostics = _unresolved_diagnostics(unresolved_cases, manifest)
    report = {
        "answerable_cases": len(answerable),
        "resolved_gold_cases": resolved,
        "gold_resolution_rate": rate,
        "minimum_gold_resolution_rate": minimum_rate,
        "unresolved_gold_case_ids": unresolved,
        "unresolved_gold_diagnostics": diagnostics,
        # Reported, never silent. Excluding a case without saying so is the
        # failure this preflight was added to catch.
        "retired_cases": len(withdrawn),
        "retired_case_reasons": {
            str(case.get("id")): str(case.get("retired_reason") or "")
            for case in withdrawn
        },
    }
    if rate < minimum_rate:
        preview = ", ".join(unresolved[:10])
        remainder = len(unresolved) - min(len(unresolved), 10)
        suffix = f" (+{remainder} more)" if remainder else ""
        raise ValueError(
            "Gold resolution preflight failed: "
            f"{resolved}/{len(answerable)} ({rate:.3f}) resolved; "
            f"minimum is {minimum_rate:.3f}. "
            f"{diagnostics['repointable_cases']} unresolved predicates name a "
            "value the corpus carries under a different manifest field "
            "(repoint them); "
            f"{diagnostics['absent_from_corpus_cases']} name a value absent "
            "from the corpus entirely (re-ingest or retire). "
            f"Unresolved: {preview}{suffix}"
        )
    return report


def _chunk_ids(documents: list[Any]) -> list[str]:
    return [str(document.metadata.get("chunk_id") or "") for document in documents]


async def _run_case(
    case: dict[str, Any],
    *,
    manifest: dict[str, dict[str, str]],
    retriever: ChromaAccessRetriever,
    sparse: BM25Retriever,
    fusion: ReciprocalRankFusion,
    reranker: Any,
    settings: Settings,
    lexical_enabled: bool = True,
) -> dict[str, Any]:
    question = str(case["question"])
    fused = await _retrieve_fused(
        question,
        retriever=retriever,
        fusion=fusion,
        settings=settings,
        lexical_enabled=lexical_enabled,
    )
    candidate_limit = (
        settings.inventory_cross_encoder_candidate_limit
        if str(case.get("suite") or "") == "registry_keys"
        else settings.cross_encoder_candidate_limit
    )
    candidates = progressive_rerank_candidates(fused, candidate_limit)
    reranked = await reranker.rerank(
        question,
        candidates,
        score_threshold=settings.rerank_score_threshold,
        top_n=settings.rerank_top_n,
    )
    return _result_row(case, manifest, fused, reranked, lexical_enabled)


async def _retrieve_fused(
    question: str,
    *,
    retriever: ChromaAccessRetriever,
    fusion: ReciprocalRankFusion,
    settings: Settings,
    lexical_enabled: bool,
) -> list[Any]:
    dense = await retriever.ainvoke(question)
    lexical = await retriever.ainvoke_lexical(question) if lexical_enabled else []
    rare_terms = await retriever.ainvoke_rare_terms(question) if lexical_enabled else ()
    explicit_identifiers = _exact_identifier_tokens(question)
    exact_terms = tuple(dict.fromkeys([*explicit_identifiers, *rare_terms]))
    anchors = (
        await retriever.ainvoke_exact_identifiers(exact_terms)
        if exact_terms
        else []
    )
    anchors = _retain_explicit_identifier_anchors(
        anchors, _forced_anchor_tokens(question)
    )
    dense_by_id = {
        str(document.metadata.get("chunk_id") or id(document)): document
        for document in [*anchors, *dense]
    }
    dense = list(dense_by_id.values())
    fused = fusion.fuse(
        lexical,
        dense,
        limit=max(settings.max_candidates, settings.retrieval_top_k),
    )
    query_terms = _exact_terms(question)
    source_candidate_counts = Counter(
        _source_identity(document) for document in fused
    )
    for document in fused:
        ratio = _exact_term_ratio(query_terms, document.page_content)
        document.metadata["exact_term_ratio"] = ratio
        boosted_score = float(
            document.metadata.get("fusion_score") or 0.0
        ) * (1 + settings.exact_term_boost * ratio)
        source_identity = _source_identity(document)
        document.metadata["source_candidate_count"] = source_candidate_counts[
            source_identity
        ]
        document.metadata["retrieval_fused_score"] = _source_volume_discounted_score(
            boosted_score,
            source_candidate_count=source_candidate_counts[source_identity],
            strength=settings.source_volume_discount_strength,
        )
    responsive, _prefilter_reasons = _prefilter_candidates(
        fused,
        minimum_dense_score=settings.prefilter_min_dense_score,
        maximum_removed_fraction=settings.prefilter_max_removed_fraction,
    )
    fused = deduplicate_candidate_bodies(
        sorted(
            responsive,
            key=lambda value: float(
                value.metadata.get("retrieval_fused_score") or 0.0
            ),
            reverse=True,
        )
    )[: settings.max_candidates]
    return fused


def _result_row(
    case: dict[str, Any],
    manifest: dict[str, dict[str, str]],
    fused: list[Any],
    reranked: list[Any],
    lexical_enabled: bool,
) -> dict[str, Any]:
    gold = _gold_ids(case, manifest)
    retrieved_ids = _chunk_ids(fused)
    reranked_ids = _chunk_ids(reranked)
    role = str(case.get("role") or "answer_evidence")
    surviving_pool = retrieved_ids if role == "navigation" else reranked_ids
    answered = bool(set(gold).intersection(surviving_pool))
    return {
        "id": case.get("id"),
        "suite": case.get("suite"),
        "query_language": case.get("query_language") or "und",
        "target_evidence_language": case.get("target_evidence_language") or "und",
        "role": role,
        "gold_chunk_ids": gold,
        "retrieved_chunk_ids": retrieved_ids,
        "reranked_chunk_ids": reranked_ids,
        "evidence_source_ids": [
            str(document.metadata.get("source_id") or "") for document in reranked
        ],
        "cited_source_ids": [],
        "exposed_project_ids": [
            str(document.metadata.get("project_id") or "")
            for document in [*fused, *reranked]
        ],
        "answerable": bool(case.get("answerable")),
        "answered": answered,
        "lexical_enabled": lexical_enabled,
    }


def _document_identity(document: Any) -> str:
    return str(
        document.metadata.get("chunk_id")
        or document.metadata.get("source_id")
        or id(document)
    )


def _select_scored(
    question: str,
    candidates: list[Any],
    scores: dict[str, float],
    *,
    threshold: float,
    top_n: int,
    max_chunks_per_source: int,
    settings: Settings,
) -> list[Any]:
    eligible: list[tuple[float, Any, str]] = []
    for document in candidates:
        score_value = scores[_document_identity(document)]
        exact_code_match = (
            score_value >= settings.exact_code_rerank_score_threshold
            and float(document.metadata.get("score") or 0)
            >= settings.exact_code_retrieval_score_floor
            and _exact_code_anchor_match(question, document)
        )
        if score_value < threshold and not exact_code_match:
            continue
        source_id = str(
            document.metadata.get("source_id")
            or document.metadata.get("reference")
            or document.metadata.get("chunk_id")
        )
        eligible.append((score_value, document, source_id))
    selected: list[Any] = []
    source_counts: dict[str, int] = {}
    for score_value, document, source_id in sorted(eligible, reverse=True, key=lambda item: item[0]):
        if source_counts.get(source_id, 0) >= max_chunks_per_source:
            continue
        source_counts[source_id] = source_counts.get(source_id, 0) + 1
        document.metadata["rerank_score"] = score_value
        selected.append(document)
        if len(selected) >= top_n:
            break
    return selected


async def _run_reranker_sweep(
    cases: list[dict[str, Any]],
    *,
    manifest: dict[str, dict[str, str]],
    retriever: ChromaAccessRetriever,
    fusion: ReciprocalRankFusion,
    reranker: Any,
    settings: Settings,
    output: Path,
    recorded_candidates: dict[str, list[Any]] | None = None,
) -> dict[str, dict[str, float | int]]:
    rows_by_name: dict[str, list[dict[str, Any]]] = {
        config[0]: [] for config in _RERANK_SWEEP
    }
    max_limit = max(max(config[1], config[2]) for config in _RERANK_SWEEP)
    prepared: list[tuple[dict[str, Any], str, list[Any], list[Any]]] = []
    score_cache_path = output.with_name(f"{output.stem}.scores.json")
    score_cache: dict[str, float] = (
        json.loads(score_cache_path.read_text(encoding="utf-8"))
        if score_cache_path.exists()
        else {}
    )
    missing_keys: list[str] = []
    missing_pairs: list[tuple[str, str]] = []
    for position, case in enumerate(cases, start=1):
        question = str(case["question"])
        fused = (
            list(recorded_candidates.get(str(case.get("id")), []))
            if recorded_candidates is not None
            else await _retrieve_fused(
                question,
                retriever=retriever,
                fusion=fusion,
                settings=settings,
                lexical_enabled=True,
            )
        )
        if not fused:
            raise RuntimeError(f"No sweep candidates for {case.get('id')}")
        maximal = progressive_rerank_candidates(fused, max_limit)
        prepared.append((case, question, fused, maximal))
        for document in maximal:
            score_key = f"{case.get('id')}|{_document_identity(document)}"
            if score_key in score_cache:
                continue
            missing_keys.append(score_key)
            missing_pairs.append(
                (
                    question,
                    scoring_evidence(
                        document.page_content,
                        linearize_tables_enabled=settings.linearize_table_evidence,
                    ),
                )
            )
        print(f"sweep_retrieval={position}/{len(cases)} id={case.get('id')}", flush=True)
    # Keep each invocation at one MPS batch. Larger input lists caused the
    # sentence-transformers data loader to spend minutes staging a single call
    # on the validated laptop, despite using the same internal batch size.
    score_batch_size = 20
    for offset in range(0, len(missing_pairs), score_batch_size):
        batch_pairs = missing_pairs[offset : offset + score_batch_size]
        batch_keys = missing_keys[offset : offset + score_batch_size]
        raw_scores = await asyncio.to_thread(
            predict_local_scores,
            settings.local_models_path or settings.local_rerank_model,
            device=settings.local_rerank_device,
            revision=settings.local_rerank_revision,
            pairs=batch_pairs,
            batch_size=settings.local_rerank_batch_size,
        )
        score_cache.update(
            {
                key: normalized_relevance_score(float(raw))
                for key, raw in zip(batch_keys, raw_scores, strict=True)
            }
        )
        score_cache_path.write_text(
            json.dumps(score_cache, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(
            f"sweep_score_pairs={min(offset + score_batch_size, len(missing_pairs))}/"
            f"{len(missing_pairs)}",
            flush=True,
        )
    for position, (case, question, fused, maximal) in enumerate(prepared, start=1):
        scores = {
            _document_identity(document): score_cache[
                f"{case.get('id')}|{_document_identity(document)}"
            ]
            for document in maximal
        }
        for name, regular_limit, inventory_limit, top_n, threshold, source_limit in _RERANK_SWEEP:
            limit = inventory_limit if case.get("suite") == "registry_keys" else regular_limit
            candidates = progressive_rerank_candidates(fused, limit)
            missing = [item for item in candidates if _document_identity(item) not in scores]
            if missing:
                raise RuntimeError(f"Sweep candidate nesting failed for {case.get('id')}")
            reranked = _select_scored(
                question,
                candidates,
                scores,
                threshold=threshold,
                top_n=top_n,
                max_chunks_per_source=source_limit,
                settings=settings,
            )
            rows_by_name[name].append(_result_row(case, manifest, fused, reranked, True))
        print(f"sweep_scored={position}/{len(cases)} id={case.get('id')}", flush=True)
    summaries: dict[str, dict[str, float | int]] = {}
    for name, rows in rows_by_name.items():
        row_path = output.with_name(f"{output.stem}.{name}.jsonl")
        row_path.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        summaries[name] = score(rows, settings=settings, project_id=str(cases[0]["project_id"]))
    output.write_text(json.dumps(summaries, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summaries


def _load_recorded_candidates(path: Path, collection: Any) -> dict[str, list[Any]]:
    """Rehydrate one accepted fused pool so a sweep changes ranking only."""

    rows = _load_jsonl(path)
    wanted = {
        str(chunk_id)
        for row in rows
        for chunk_id in row.get("retrieved_chunk_ids", [])
        if str(chunk_id)
    }
    by_id: dict[str, Any] = {}
    offset = 0
    while wanted - by_id.keys():
        response = collection.get(
            limit=500,
            offset=offset,
            include=["documents", "metadatas"],
        )
        identifiers = response.get("ids", [])
        for chunk_id, content, metadata in zip(
            identifiers,
            response.get("documents", []),
            response.get("metadatas", []),
            strict=True,
        ):
            values = dict(metadata or {})
            canonical_id = str(
                values.get("canonical_chunk_id")
                or values.get("chunk_id")
                or chunk_id
            )
            if canonical_id in wanted:
                values["chunk_id"] = canonical_id
                by_id[canonical_id] = Document(
                    page_content=str(content or ""), metadata=values
                )
        offset += len(identifiers)
        if len(identifiers) < 500:
            break
    missing = wanted - by_id.keys()
    if missing:
        raise RuntimeError(f"Recorded sweep candidates missing from Chroma: {sorted(missing)[:5]}")
    result: dict[str, list[Any]] = {}
    for row in rows:
        ordered = [
            Document(
                page_content=by_id[str(chunk_id)].page_content,
                metadata=dict(by_id[str(chunk_id)].metadata),
            )
            for chunk_id in row.get("retrieved_chunk_ids", [])
            if str(chunk_id) in by_id
        ]
        total = max(1, len(ordered))
        for index, document in enumerate(ordered):
            document.metadata["retrieval_fused_score"] = (total - index) / total
        result[str(row.get("id"))] = ordered
    return result


async def _main(arguments: argparse.Namespace) -> None:
    overrides: dict[str, Any] = {
        "chroma_host": arguments.chroma_host,
        "chroma_port": arguments.chroma_port,
        "chroma_collection": arguments.collection,
    }
    for name in (
        "cross_encoder_candidate_limit",
        "inventory_cross_encoder_candidate_limit",
        "rerank_top_n",
        "rerank_score_threshold",
        "max_chunks_per_source",
    ):
        value = getattr(arguments, name, None)
        if value is not None:
            overrides[name] = value
    settings = Settings(**overrides)
    physical_name = project_collection_name(arguments.collection, arguments.project_id)
    collection = HttpClient(
        host=arguments.chroma_host, port=arguments.chroma_port
    ).get_collection(physical_name)
    verify_project_collection(collection, arguments.collection, arguments.project_id)
    manifest = _namespace_manifest(
        collection,
        project_id=arguments.project_id,
        logical_collection=arguments.collection,
        cache_path=_manifest_cache_path(arguments.out),
    )
    retriever = ChromaAccessRetriever.create(
        chroma_host=arguments.chroma_host,
        chroma_port=arguments.chroma_port,
        collection_name=arguments.collection,
        text_field="chunk_text",
        project_id=arguments.project_id,
        access_policy_ids=(f"project:{arguments.project_id}",),
        top_k=settings.retrieval_top_k,
        score_threshold=settings.retrieval_score_threshold,
        required_schema_version=settings.supported_schema_versions[0],
        required_embedding_model=settings.supported_embedding_models[0],
        retry_attempts=settings.dependency_retry_attempts,
        timeout_seconds=settings.dependency_timeout_seconds,
        lexical_fallback_enabled=settings.lexical_fallback_enabled,
        lexical_fallback_max_records=settings.lexical_fallback_max_records,
        lexical_fallback_cache_ttl_seconds=settings.lexical_fallback_cache_ttl_seconds,
        vocabulary_cache_ttl_seconds=settings.vocabulary_cache_ttl_seconds,
        embedder=build_embedder(settings),
    )
    sparse = BM25Retriever()
    fusion = ReciprocalRankFusion(
        k=settings.rank_fusion_k,
        lexical_weight=settings.lexical_fusion_weight,
        dense_weight=settings.dense_fusion_weight,
    )
    reranker = build_reranker(settings)
    all_cases = _load_evaluation_cases(arguments.suites)
    if arguments.ragas_references:
        all_cases = _apply_reviewed_references(
            all_cases,
            arguments.ragas_references,
            expected_dataset_version=arguments.dataset_version,
        )
    cases = [
        case
        for case in all_cases
        if case.get("evaluation_lane") != "generation"
        and case.get("retired") is not True
    ]
    wrong_project = [case.get("id") for case in all_cases if case.get("project_id") != arguments.project_id]
    if wrong_project:
        raise ValueError(
            f"Suite cases do not belong to {arguments.project_id}: {wrong_project[:5]}"
        )
    gold_resolution = _validate_gold_resolution(
        cases,
        manifest,
        minimum_rate=arguments.minimum_gold_resolution_rate,
    )
    print("GOLD_RESOLUTION_PREFLIGHT", flush=True)
    print(json.dumps(gold_resolution, indent=2, sort_keys=True), flush=True)
    if arguments.reranker_sweep_out:
        recorded_candidates = (
            _load_recorded_candidates(arguments.sweep_candidates_from, collection)
            if arguments.sweep_candidates_from
            else None
        )
        summaries = await _run_reranker_sweep(
            cases,
            manifest=manifest,
            retriever=retriever,
            fusion=fusion,
            reranker=reranker,
            settings=settings,
            output=arguments.reranker_sweep_out,
            recorded_candidates=recorded_candidates,
        )
        print(json.dumps(summaries, indent=2, sort_keys=True))
        return
    rows = _load_jsonl(arguments.out) if arguments.out.exists() else []
    completed = {str(row.get("id")) for row in rows}
    for position, case in enumerate(cases, start=1):
        if str(case.get("id")) in completed:
            continue
        row = await _run_case(
            case,
            manifest=manifest,
            retriever=retriever,
            sparse=sparse,
            fusion=fusion,
            reranker=reranker,
            settings=settings,
            lexical_enabled=not arguments.disable_lexical,
        )
        rows.append(row)
        arguments.out.write_text(
            "".join(json.dumps(value, sort_keys=True) + "\n" for value in rows),
            encoding="utf-8",
        )
        print(f"case={position}/{len(cases)} id={case.get('id')}", flush=True)
    arguments.out.write_text(
        "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
        encoding="utf-8",
    )
    summary = score(rows, settings=settings, project_id=arguments.project_id)
    summary_path = arguments.out.with_suffix(".json")
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    _publish_retrieval_quality(summary, settings=settings, arguments=arguments)
    if arguments.generate:
        generation_out = arguments.generation_out or arguments.out.with_name(
            f"{arguments.out.stem}.generation.jsonl"
        )
        generation_rows = await _run_generation_lane(
            _generation_sample(all_cases, arguments.generate),
            settings=settings,
            project_id=arguments.project_id,
            output=generation_out,
        )
        generation_summary = score_generation(generation_rows)
        generation_out.with_suffix(".json").write_text(
            json.dumps(generation_summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print("GENERATION_LANE", flush=True)
        print(json.dumps(generation_summary, indent=2, sort_keys=True))
        _publish_generation_quality(
            generation_summary, settings=settings, arguments=arguments
        )
    if arguments.ragas_references:
        ragas_cases = _reviewed_bilingual_ragas_cases(all_cases)
        bilingual_generation_cases = [
            case
            for case in all_cases
            if case.get("suite") == "bilingual_curated"
            and case.get("retired") is not True
        ]
        generation_output = arguments.ragas_out.with_name(
            f"{arguments.ragas_out.stem}.generation.jsonl"
        )
        generation_rows = await _run_generation_lane(
            bilingual_generation_cases,
            settings=settings,
            project_id=arguments.project_id,
            output=generation_output,
        )
        generation_summary = score_generation(generation_rows)
        generation_summary_path = generation_output.with_suffix(".json")
        generation_summary_path.write_text(
            json.dumps(generation_summary, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        ragas_ids = {str(case.get("id")) for case in ragas_cases}
        ragas_rows = [row for row in generation_rows if str(row.get("id")) in ragas_ids]
        if len(ragas_rows) != len(ragas_cases):
            raise RuntimeError(
                "Bilingual RAGAS input is incomplete: "
                f"expected {len(ragas_cases)} rows, found {len(ragas_rows)}"
            )
        arguments.ragas_out.parent.mkdir(parents=True, exist_ok=True)
        arguments.ragas_out.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in ragas_rows),
            encoding="utf-8",
        )
        print("BILINGUAL_GENERATION_DIAGNOSTICS", flush=True)
        print(json.dumps(generation_summary, indent=2, sort_keys=True))
        _publish_generation_quality(
            generation_summary, settings=settings, arguments=arguments
        )


def _publish_retrieval_quality(
    summary: dict[str, object], *, settings: Settings, arguments: argparse.Namespace
) -> None:
    """Publish only content-free retrieval aggregates to the Phoenix quality project."""

    if not arguments.phoenix_url:
        return
    from app.openinference_tracing import configure_openinference

    tracing_settings = settings.model_copy(
        update={
            "openinference_enabled": True,
            "openinference_otlp_endpoint": arguments.openinference_otlp_endpoint,
        }
    )
    provider = configure_openinference(tracing_settings)
    if provider is None:
        return
    try:
        tracer = provider.get_tracer("project-intelligence-quality")
        with tracer.start_as_current_span(
            "rag.quality.retrieval",
            attributes={
                "openinference.span.kind": "CHAIN",
                "quality.section": "retrieval",
                "quality.run_id": arguments.quality_run_id or "standalone",
                "quality.sample_count": int(summary.get("cases", 0)),
            },
        ) as span:
            span_id = format(span.get_span_context().span_id, "016x")
        provider.force_flush()
        publish_scores_to_phoenix(
            arguments.phoenix_url,
            span_id,
            retrieval_dashboard_scores(summary),
            int(summary.get("cases", 0)),
            section="retrieval",
            annotator_kind="CODE",
            metadata={
                "run_id": arguments.quality_run_id or "standalone",
                "project_id": arguments.project_id,
                "dataset_version": arguments.dataset_version,
                "commit_sha": arguments.commit_sha,
                "embedding_model": settings.local_embedding_model,
                "rerank_model": settings.local_rerank_model,
                "sample_count_en": int(
                    (summary.get("by_query_language", {}) or {}).get("en", {}).get("cases", 0)
                ),
                "sample_count_es": int(
                    (summary.get("by_query_language", {}) or {}).get("es", {}).get("cases", 0)
                ),
                "retrieval_top_k": settings.retrieval_top_k,
                "rerank_top_n": settings.rerank_top_n,
            },
            sample_counts=retrieval_dashboard_sample_counts(summary),
        )
    finally:
        provider.shutdown()


def _publish_generation_quality(
    summary: dict[str, object], *, settings: Settings, arguments: argparse.Namespace
) -> None:
    """Publish content-free deterministic generation diagnostics to Phoenix."""

    if not arguments.phoenix_url:
        return
    from app.openinference_tracing import configure_openinference

    tracing_settings = settings.model_copy(
        update={
            "openinference_enabled": True,
            "openinference_otlp_endpoint": arguments.openinference_otlp_endpoint,
        }
    )
    provider = configure_openinference(tracing_settings)
    if provider is None:
        return
    try:
        tracer = provider.get_tracer("project-intelligence-quality")
        with tracer.start_as_current_span(
            "rag.quality.answer_generation",
            attributes={
                "openinference.span.kind": "CHAIN",
                "quality.section": "answer_generation",
                "quality.run_id": arguments.quality_run_id or "standalone",
                "quality.sample_count": int(summary.get("cases", 0)),
                "quality.evaluator": "deterministic",
            },
        ) as span:
            span_id = format(span.get_span_context().span_id, "016x")
        provider.force_flush()
        publish_scores_to_phoenix(
            arguments.phoenix_url,
            span_id,
            generation_dashboard_scores(summary),
            int(summary.get("cases", 0)),
            section="answer_generation",
            annotator_kind="CODE",
            metadata={
                "run_id": arguments.quality_run_id or "standalone",
                "project_id": arguments.project_id,
                "dataset_version": arguments.dataset_version,
                "commit_sha": arguments.commit_sha,
                "sample_count_en": int(
                    (summary.get("by_query_language", {}) or {}).get("en", {}).get("cases", 0)
                ),
                "sample_count_es": int(
                    (summary.get("by_query_language", {}) or {}).get("es", {}).get("cases", 0)
                ),
            },
            sample_counts=generation_dashboard_sample_counts(summary),
        )
    finally:
        provider.shutdown()


def _stratified_sample(cases: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Round-robin suites, answerability, and negative reason categories."""

    groups: dict[tuple[object, ...], deque[dict[str, Any]]] = defaultdict(deque)
    for case in cases:
        key = (
            case.get("suite"),
            case.get("query_language") or "und",
            bool(case.get("answerable")),
            case.get("expected_refusal_reason"),
        )
        groups[key].append(case)
    selected: list[dict[str, Any]] = []
    active = deque(sorted(groups, key=lambda value: tuple(str(item) for item in value)))
    while active and len(selected) < min(size, len(cases)):
        key = active.popleft()
        selected.append(groups[key].popleft())
        if groups[key]:
            active.append(key)
    return selected


def _generation_sample(
    cases: list[dict[str, Any]], size: int
) -> list[dict[str, Any]]:
    """Reserve nightly generation capacity for every paraphrase invariant."""

    paraphrases = json.loads(_PARAPHRASE_GROUPS_PATH.read_text(encoding="utf-8"))
    paraphrases = [
        {**case, "suite": "paraphrase_invariance", "evaluation_lane": "generation"}
        for case in paraphrases
    ]
    remaining = max(0, size - len(paraphrases))
    return [*paraphrases, *_stratified_sample(cases, remaining)]


async def _run_generation_lane(
    cases: list[dict[str, Any]],
    *,
    settings: Settings,
    project_id: str,
    output: Path,
) -> list[dict[str, Any]]:
    selected_ids = {str(case.get("id")) for case in cases}
    rows = [
        row
        for row in (_load_jsonl(output) if output.exists() else [])
        if str(row.get("id")) in selected_ids
    ]
    completed = {str(row.get("id")) for row in rows}
    for position, case in enumerate(cases, start=1):
        if str(case.get("id")) in completed:
            continue
        request = RagRequest(
            projectId=project_id,
            collectionName=settings.chroma_collection,
            textField="chunk_text",
            embeddingField="embedding_text",
            embeddingModel=settings.supported_embedding_models[0],
            schemaVersion=settings.supported_schema_versions[0],
            question=str(case["question"]),
            accessPolicyIds=[f"project:{project_id}"],
            modelProfile="budget",
        )
        evaluation_result = await AuthorizedRagWorkflow(
            settings, request
        ).run_for_evaluation()
        response = evaluation_result.response
        cited = [source.reference for source in response.sources if source.reference]
        row = {
            "id": case.get("id"),
            "case_id": case.get("id"),
            "suite": case.get("suite"),
            "query_language": case.get("query_language") or "und",
            "target_evidence_language": case.get("target_evidence_language") or "und",
            "paraphrase_group": case.get("paraphrase_group"),
            "answerable": bool(case.get("answerable")),
            "answered": response.confidence != "NONE",
            "grounding_accepted": response.evidence_status == "SUFFICIENT",
            "cited_source_ids": cited,
            "valid_citation_count": len(cited),
            "uncited_claims_dropped": evaluation_result.uncited_claims_dropped,
            "refusal_reason": response.refusal_reason,
            "expected_refusal_reason": case.get("expected_refusal_reason"),
        }
        if case.get("reference") and case.get("reference_status") == "reviewed":
            row.update(
                {
                    "user_input": str(case["question"]),
                    "response": response.answer,
                    "retrieved_contexts": list(evaluation_result.retrieved_contexts),
                    "reference": str(case["reference"]),
                    "reference_status": "reviewed",
                    "dataset_version": case.get("dataset_version", "1"),
                }
            )
        rows.append(row)
        output.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        print(f"generation_case={position}/{len(cases)} id={case.get('id')}", flush=True)
    if len(rows) != len(cases):
        raise RuntimeError(
            "Generation lane output is incomplete or duplicated: "
            f"expected {len(cases)} rows, found {len(rows)}"
        )
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--chroma-host", default="127.0.0.1")
    parser.add_argument("--chroma-port", type=int, default=8000)
    parser.add_argument("--collection", default="project-intelligence")
    parser.add_argument(
        "--disable-lexical",
        action="store_true",
        help="Run an ablation with the sparse channel removed.",
    )
    parser.add_argument(
        "--suites",
        type=Path,
        default=_DEFAULT_SUITES_PATH,
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--generate",
        type=int,
        choices=range(30, 41),
        metavar="N",
        help="Run full generation, citation validation, and grounding on 30-40 cases.",
    )
    parser.add_argument("--generation-out", type=Path)
    parser.add_argument(
        "--ragas-references",
        type=Path,
        help="Reviewed reference-answer JSONL joined by bilingual case_id.",
    )
    parser.add_argument(
        "--ragas-out",
        type=Path,
        default=Path(".quality-runs/ragas-generated.jsonl"),
        help="Local content-bearing RAGAS input generated from the production workflow.",
    )
    parser.add_argument(
        "--minimum-gold-resolution-rate",
        type=float,
        default=_MINIMUM_GOLD_RESOLUTION_RATE,
        help="Abort before retrieval when fewer answerable cases resolve to live chunks.",
    )
    parser.add_argument("--cross-encoder-candidate-limit", type=int)
    parser.add_argument("--inventory-cross-encoder-candidate-limit", type=int)
    parser.add_argument("--rerank-top-n", type=int)
    parser.add_argument("--rerank-score-threshold", type=float)
    parser.add_argument("--max-chunks-per-source", type=int)
    parser.add_argument(
        "--phoenix-url",
        default=os.getenv("PI_RAG_PHOENIX_URL", ""),
        help="Publish aggregate retrieval quality annotations to Phoenix when set.",
    )
    parser.add_argument(
        "--openinference-otlp-endpoint",
        default=os.getenv(
            "PI_RAG_OPENINFERENCE_OTLP_ENDPOINT", "http://127.0.0.1:4318/v1/traces"
        ),
    )
    parser.add_argument("--quality-run-id", default=os.getenv("PI_RAG_QUALITY_RUN_ID", ""))
    parser.add_argument("--dataset-version", default=os.getenv("PI_RAG_DATASET_VERSION", "1"))
    parser.add_argument("--commit-sha", default=os.getenv("PI_RAG_COMMIT_SHA", "unknown"))
    parser.add_argument(
        "--reranker-sweep-out",
        type=Path,
        help="Score the built-in reranker matrix from one shared candidate pass.",
    )
    parser.add_argument(
        "--sweep-candidates-from",
        type=Path,
        help="Reuse a recorded fused retrieval pool so only reranker settings vary.",
    )
    asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    main()
