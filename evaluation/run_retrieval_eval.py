"""Run the real local retrieval and reranking path against a gold suite."""

from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict, deque
import json
from pathlib import Path
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
    from evaluation.score import score, score_generation
except ModuleNotFoundError:  # Direct `python evaluation/run_retrieval_eval.py` execution.
    from score import score, score_generation


_MANIFEST_FIELDS = ("structure_path", "title", "source_id", "doc_category")
_MANIFEST_VERSION = 2
_PARAPHRASE_GROUPS_PATH = Path(__file__).with_name("paraphrase_groups.json")
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
    matches: list[str] = []
    for chunk_id, metadata in manifest.items():
        for predicate in predicates:
            field = str(predicate.get("field") or "")
            expected = str(predicate.get("contains") or "").casefold()
            if field in _MANIFEST_FIELDS and expected in metadata[field].casefold():
                matches.append(chunk_id)
                break
    return matches


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
    all_cases = _load_jsonl(arguments.suites)
    cases = [case for case in all_cases if case.get("evaluation_lane") != "generation"]
    wrong_project = [case.get("id") for case in all_cases if case.get("project_id") != arguments.project_id]
    if wrong_project:
        raise ValueError(
            f"Suite cases do not belong to {arguments.project_id}: {wrong_project[:5]}"
        )
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


def _stratified_sample(cases: list[dict[str, Any]], size: int) -> list[dict[str, Any]]:
    """Round-robin suites, answerability, and negative reason categories."""

    groups: dict[tuple[object, ...], deque[dict[str, Any]]] = defaultdict(deque)
    for case in cases:
        key = (
            case.get("suite"),
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
        response = await AuthorizedRagWorkflow(settings, request).run()
        cited = [source.reference for source in response.sources if source.reference]
        rows.append(
            {
                "id": case.get("id"),
                "suite": case.get("suite"),
                "paraphrase_group": case.get("paraphrase_group"),
                "answerable": bool(case.get("answerable")),
                "answered": response.confidence != "NONE",
                "grounding_accepted": response.evidence_status == "SUFFICIENT",
                "cited_source_ids": cited,
                "valid_citation_count": len(cited),
                "refusal_reason": response.refusal_reason,
                "expected_refusal_reason": case.get("expected_refusal_reason"),
            }
        )
        output.write_text(
            "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
            encoding="utf-8",
        )
        print(f"generation_case={position}/{len(cases)} id={case.get('id')}", flush=True)
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
        default=Path(__file__).with_name("gold_suites.jsonl"),
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
    parser.add_argument("--cross-encoder-candidate-limit", type=int)
    parser.add_argument("--inventory-cross-encoder-candidate-limit", type=int)
    parser.add_argument("--rerank-top-n", type=int)
    parser.add_argument("--rerank-score-threshold", type=float)
    parser.add_argument("--max-chunks-per-source", type=int)
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
