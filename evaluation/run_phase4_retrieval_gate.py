"""Self-generating Phase 4 identifier and section retrieval gate."""

from __future__ import annotations

import argparse
import json
import re

from chromadb import HttpClient

from app.retrieval import ChromaAccessRetriever
from app.chroma_collections import project_collection_name, verify_project_collection


REGISTRY_ROW = re.compile(
    r"(?m)^\s*`?([A-Z][A-Z0-9_]+)`?\s*\|\s*`?([A-Z][A-Z0-9_]+)`?\s*\|"
    r"\s*(\d+)\s*\|\s*([0-9]+(?:[.,][0-9]+)*)\s*\|"
)
SECTION_ID = re.compile(r"\[([A-Z][A-Z0-9]*-\d{3})\]")
POS_LOGIN_FIELDS = {
    "eventType", "eventId", "versionNumber", "user", "eventDateTime",
    "operationDate", "storeId", "posId", "status", "sessionId", "message",
}


def registry_entries(documents: list[str]) -> dict[str, tuple[str, str, str]]:
    entries: dict[str, tuple[str, str, str]] = {}
    for document in documents:
        for constant, wire_name, event_id, version in REGISTRY_ROW.findall(document):
            entries.setdefault(wire_name, (constant, event_id, version.replace(",", ".")))
    return entries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--collection", default="project-intelligence")
    arguments = parser.parse_args()

    physical_name = project_collection_name(arguments.collection, arguments.project_id)
    collection = HttpClient(host=arguments.host, port=arguments.port).get_collection(physical_name)
    verify_project_collection(collection, arguments.collection, arguments.project_id)
    corpus = collection.get(
        where={"$and": [
            {"project_id": arguments.project_id},
            {"access_policy_id": f"project:{arguments.project_id}"},
        ]},
        include=["documents", "metadatas"],
    )
    documents = [str(value or "") for value in corpus.get("documents", [])]
    entries = registry_entries(documents)
    section_ids = sorted({identifier for document in documents for identifier in SECTION_ID.findall(document)})
    if len(entries) < 27:
        raise SystemExit(f"Only {len(entries)} event registry cases were derivable; expected at least 27.")

    retriever = ChromaAccessRetriever(
        index=collection,
        collection_name=physical_name,
        project_id=arguments.project_id,
        access_policy_ids=(f"project:{arguments.project_id}",),
        required_schema_version="3",
        required_embedding_model="multilingual-e5-large",
        score_threshold=0.0,
        top_k=25,
    )
    identifier_failures: list[str] = []
    pos_login_complete = False
    for wire_name, (constant, _event_id, _version) in sorted(entries.items()):
        evidence = retriever._exact_identifier_documents(
            (wire_name, constant), ("PAGE", "CODE")
        )
        haystack = "\n".join(document.page_content for document in evidence)
        if wire_name not in haystack or constant not in haystack:
            identifier_failures.append(wire_name)
        if wire_name == "POS_LOGIN":
            pos_login_complete = (
                "LoginEvent.kt" in " ".join(str(document.metadata.get("title")) for document in evidence)
                and POS_LOGIN_FIELDS <= set(re.findall(r"\b[A-Za-z][A-Za-z0-9]+\b", haystack))
            )

    section_failures: list[str] = []
    for section_id in section_ids:
        response = collection.get(
            where={"$and": [
                {"project_id": arguments.project_id},
                {"access_policy_id": f"project:{arguments.project_id}"},
            ]},
            where_document={"$contains": section_id},
            include=[],
        )
        if not response.get("ids"):
            section_failures.append(section_id)

    result = {
        "identifier_cases": len(entries),
        "identifier_recall": (len(entries) - len(identifier_failures)) / len(entries),
        "identifier_failures": identifier_failures,
        "section_cases": len(section_ids),
        "section_recall": 1.0 if not section_ids else (len(section_ids) - len(section_failures)) / len(section_ids),
        "section_failures": section_failures,
        "pos_login_complete": pos_login_complete,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    if identifier_failures or section_failures or not pos_login_complete:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
