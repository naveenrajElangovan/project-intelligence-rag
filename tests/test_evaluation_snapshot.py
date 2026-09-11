import json

import pytest

from app.chroma_collections import project_collection_name
from app.evaluation_snapshot import SnapshotRequest, collection_snapshot


class Collection:
    def __init__(self):
        self.name = project_collection_name("jira-stage-generic-123", "OPS")
        self.metadata = {
            "project_id": "OPS",
            "logical_collection": "jira-stage-generic-123",
            "hnsw:space": "cosine",
            "jira_run_contract": json.dumps(
                {
                    "project_id": "OPS",
                    "run_id": "generic-123",
                    "phase": "full-stage",
                    "logical_collection": "jira-stage-generic-123",
                    "embedding_model": "multilingual-e5-large",
                    "schema_version": "3",
                }
            ),
        }
        self.rows = [
            (str(index), "content", {"project_id": "OPS"}, [1.0, 2.0]) for index in range(101)
        ]

    def count(self):
        return len(self.rows)

    def get(self, limit, offset, include):
        return dict(
            zip(
                ("ids", "documents", "metadatas", "embeddings"),
                zip(*self.rows[offset : offset + limit], strict=True),
                strict=True,
            )
        )


def test_snapshot_covers_all_pages_vectors_and_metadata():
    collection = Collection()
    request = SnapshotRequest(project_id="OPS", ingestion_run_id="generic-123")
    snapshot = collection_snapshot(collection, request)
    assert snapshot["record_count"] == 101
    assert collection_snapshot(collection, request) == snapshot
    collection.rows[-1][3][0] = 3.0
    assert (
        collection_snapshot(collection, request)["inventory_sha256"] != snapshot["inventory_sha256"]
    )


@pytest.mark.parametrize("defect", ["project", "duplicate", "canary", "empty"])
def test_invalid_snapshot_fails_closed(defect):
    collection = Collection()
    if defect == "project":
        collection.rows[-1][2]["project_id"] = "OTHER"
    elif defect == "duplicate":
        collection.rows[-1] = collection.rows[0]
    elif defect == "empty":
        collection.rows = []
    else:
        collection.metadata["jira_run_contract"] = collection.metadata["jira_run_contract"].replace(
            "full-stage", "canary"
        )
    with pytest.raises(ValueError):
        collection_snapshot(
            collection, SnapshotRequest(project_id="OPS", ingestion_run_id="generic-123")
        )
