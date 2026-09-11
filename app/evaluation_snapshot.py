"""Private, content-free fingerprints for an isolated Jira evaluation target."""

import hashlib
import json

from pydantic import BaseModel, ConfigDict, Field

from app.chroma_collections import project_collection_name, verify_project_collection


class SnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_id: str = Field(min_length=1, max_length=100)
    ingestion_run_id: str = Field(pattern=r"^[a-z0-9-]{6,37}$")


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def collection_snapshot(collection, request: SnapshotRequest):
    logical = "jira-stage-" + request.ingestion_run_id
    verify_project_collection(collection, logical, request.project_id)
    contract = json.loads((collection.metadata or {}).get("jira_run_contract", "{}"))
    if (
        contract.get("project_id") != request.project_id
        or contract.get("run_id") != request.ingestion_run_id
        or contract.get("logical_collection") != logical
        or contract.get("phase") != "full-stage"
    ):
        raise ValueError("A complete staging-run contract is required")
    count = collection.count()
    if not 1 <= count <= 100000:
        raise ValueError("Evaluation inventory is empty or exceeds its bounded size")
    records = {}
    offset = 0
    while offset < count:
        page = collection.get(
            limit=100, offset=offset, include=["documents", "metadatas", "embeddings"]
        )
        if not page["ids"]:
            raise ValueError("Inventory pagination ended early")
        for identity, document, metadata, vector in zip(
            page["ids"], page["documents"], page["metadatas"], page["embeddings"], strict=True
        ):
            if identity in records or metadata.get("project_id") != request.project_id:
                raise ValueError("Duplicate or cross-project inventory record")
            records[identity] = digest([document, metadata, [float(value) for value in vector]])
        offset += len(page["ids"])
    if len(records) != count or collection.count() != count:
        raise ValueError("Inventory changed while it was inspected")
    return {
        "inventory_sha256": digest(sorted(records.items())),
        "contract_sha256": digest(contract),
        "record_count": count,
        "embedding_model": contract["embedding_model"],
        "schema_version": contract["schema_version"],
    }


def read_snapshot(settings, request):
    from app.retrieval import shared_chroma_client

    client = shared_chroma_client(settings.chroma_host, settings.chroma_port)
    collection = client.get_collection(
        project_collection_name("jira-stage-" + request.ingestion_run_id, request.project_id)
    )
    return collection_snapshot(collection, request)
