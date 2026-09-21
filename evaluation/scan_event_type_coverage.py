"""Compare an authoritative Kotlin EventType enum with the live project corpus."""

from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path

from chromadb import HttpClient

from app.chroma_collections import project_collection_name, verify_project_collection
from evaluation.run_phase4_retrieval_gate import registry_entries


def coverage_summary(
    source_text: str,
    documents: list[str],
    metadatas: list[dict[str, object]],
) -> dict[str, object]:
    expected = registry_entries([source_text])
    observed = registry_entries(documents)
    exact = {
        wire_name
        for wire_name, expected_value in expected.items()
        if observed.get(wire_name) == expected_value
    }
    missing = sorted(set(expected).difference(exact))
    mismatched = {
        wire_name: {"expected": expected[wire_name], "observed": observed.get(wire_name)}
        for wire_name in sorted(set(expected).intersection(observed).difference(exact))
    }
    entity_keys = [
        str(metadata.get("entity_key") or "").strip()
        for metadata in metadatas
        if metadata.get("record_kind") != "__vocabulary__"
    ]
    populated = [value for value in entity_keys if value]
    counts = Counter(populated)
    repository_counts = Counter(
        str(metadata.get("repository") or "")
        for metadata in metadatas
        if metadata.get("record_kind") != "__vocabulary__" and str(metadata.get("repository") or "")
    )
    provider_counts = Counter(
        str(metadata.get("provider") or "")
        for metadata in metadatas
        if metadata.get("record_kind") != "__vocabulary__"
    )
    folded_counts = Counter(value.casefold() for value in populated)
    generic = {key: folded_counts.get(key.casefold(), 0) for key in ("BOT", "POS", "IOT")}
    generic_breakdown = Counter(
        (
            str(metadata.get("entity_key") or "").strip().upper(),
            str(metadata.get("provider") or "UNKNOWN").strip().upper(),
            str(metadata.get("source_type") or "UNKNOWN").strip().upper(),
            str(metadata.get("repository") or "").strip() or "(none)",
        )
        for metadata in metadatas
        if metadata.get("record_kind") != "__vocabulary__"
        and str(metadata.get("entity_key") or "").strip().upper() in {"BOT", "POS", "IOT"}
    )
    return {
        "expected_event_types": len(expected),
        "observed_event_types": len(observed),
        "exact_event_types": len(exact),
        "coverage_rate": len(exact) / len(expected) if expected else 0.0,
        "missing_event_types": missing,
        "mismatched_event_types": mismatched,
        "corpus_chunks": len(metadatas),
        "entity_key_populated_chunks": len(populated),
        "entity_key_distinct_values": len(counts),
        "generic_entity_key_counts": generic,
        "generic_entity_key_breakdown": [
            {
                "entity_key": key[0],
                "provider": key[1],
                "source_type": key[2],
                "repository": key[3],
                "chunks": count,
            }
            for key, count in generic_breakdown.most_common()
        ],
        "entity_key_top_20": counts.most_common(20),
        "repository_counts": dict(repository_counts.most_common()),
        "provider_counts": dict(provider_counts.most_common()),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument(
        "--collection",
        default=os.getenv("PI_RAG_CHROMA_COLLECTION", "project-intelligence"),
    )
    arguments = parser.parse_args()

    physical_name = project_collection_name(arguments.collection, arguments.project_id)
    collection = HttpClient(host=arguments.host, port=arguments.port).get_collection(physical_name)
    verify_project_collection(collection, arguments.collection, arguments.project_id)
    corpus = collection.get(
        where={
            "$and": [
                {"project_id": arguments.project_id},
                {"access_policy_id": f"project:{arguments.project_id}"},
            ]
        },
        include=["documents", "metadatas"],
    )
    result = coverage_summary(
        arguments.source.read_text(encoding="utf-8"),
        [str(value or "") for value in corpus.get("documents", [])],
        [dict(value or {}) for value in corpus.get("metadatas", [])],
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    raise SystemExit(0 if result["coverage_rate"] == 1.0 else 1)


if __name__ == "__main__":
    main()
