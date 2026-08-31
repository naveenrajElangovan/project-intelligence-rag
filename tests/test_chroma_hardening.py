import pytest

from app.chroma_collections import project_collection_name, verify_project_collection


class Collection:
    def __init__(self, name: str, metadata: dict[str, str]) -> None:
        self.name = name
        self.metadata = metadata


def test_project_collection_names_are_physically_isolated() -> None:
    first = project_collection_name("project-intelligence", "DEMO")
    second = project_collection_name("project-intelligence", "OTHER")
    assert first != second


def test_read_connection_rejects_wrong_project_or_metric() -> None:
    name = project_collection_name("project-intelligence", "DEMO")
    with pytest.raises(RuntimeError):
        verify_project_collection(
            Collection(name, {"project_id": "OTHER", "logical_collection": "project-intelligence", "hnsw:space": "l2"}),
            "project-intelligence",
            "DEMO",
        )
