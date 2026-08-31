"""A collection written under a different schema must say so, not answer nothing.

Records that match the metadata filter and are then dropped during filtering are
indistinguishable, from the outside, from a collection with nothing relevant in
it. The reason is knowable only at the point of the drop.
"""

from types import SimpleNamespace

from langchain_core.documents import Document

from app.retrieval import ChromaAccessRetriever


def _retriever(**overrides) -> ChromaAccessRetriever:
    settings = dict(
        index=object(),
        collection_name="project-intelligence",
        project_id="DEMO",
        access_policy_ids=("project:DEMO",),
        required_schema_version="3",
        required_embedding_model="multilingual-e5-large",
        score_threshold=0.0,
    )
    settings.update(overrides)
    return ChromaAccessRetriever(**settings)


def _record(**overrides) -> dict[str, object]:
    record = {
        "chunk_text": "Cash relief moves drawer cash into store custody.",
        "project_id": "DEMO",
        "access_policy_id": "project:DEMO",
        "schema_version": "3",
        "embedding_model": "multilingual-e5-large",
    }
    record.update(overrides)
    return record


def test_a_matching_record_is_returned() -> None:
    drops: dict[str, int] = {}
    document = _retriever()._document_from_fields(_record(), "chunk-1", 0.9, drops)
    assert document is not None
    assert drops == {}


def test_a_stale_schema_version_names_both_values() -> None:
    drops: dict[str, int] = {}
    document = _retriever()._document_from_fields(
        _record(schema_version="2"), "chunk-1", 0.9, drops
    )
    assert document is None
    assert list(drops) == ["schema_version:expected=3,found=2"]


def test_an_absent_schema_version_is_reported_as_absent() -> None:
    drops: dict[str, int] = {}
    record = _record()
    del record["schema_version"]
    assert _retriever()._document_from_fields(record, "chunk-1", 0.9, drops) is None
    assert list(drops) == ["schema_version:expected=3,found=absent"]


def test_a_different_embedding_model_names_both_values() -> None:
    drops: dict[str, int] = {}
    document = _retriever()._document_from_fields(
        _record(embedding_model="text-embedding-3-small"), "chunk-1", 0.9, drops
    )
    assert document is None
    assert list(drops) == [
        "embedding_model:expected=multilingual-e5-large,found=text-embedding-3-small"
    ]


def test_a_foreign_project_is_reported_separately_from_a_schema_drift() -> None:
    """Cross-project leakage and schema drift must not look like the same fault."""

    drops: dict[str, int] = {}
    document = _retriever()._document_from_fields(
        _record(project_id="OTHER"), "chunk-1", 0.9, drops
    )
    assert document is None
    assert list(drops) == ["project_or_policy_mismatch"]


def test_an_empty_text_field_is_distinguished_from_a_low_score() -> None:
    drops: dict[str, int] = {}
    _retriever()._document_from_fields(_record(chunk_text=""), "a", 0.9, drops)
    assert list(drops) == ["empty_text_field"]

    drops = {}
    _retriever(score_threshold=0.5)._document_from_fields(_record(), "b", 0.1, drops)
    assert list(drops) == ["below_score_threshold"]


def test_drops_accumulate_so_the_dominant_reason_is_visible() -> None:
    retriever = _retriever()
    drops: dict[str, int] = {}
    for index in range(7):
        retriever._document_from_fields(
            _record(schema_version="2"), f"chunk-{index}", 0.9, drops
        )
    assert drops == {"schema_version:expected=3,found=2": 7}


def test_population_is_scoped_by_entity_and_family_label(monkeypatch) -> None:
    documents = (
        Document(
            page_content="### Application family (1xx)\nLOGIN_EVENT",
            metadata={
                "doc_category": "entity-contract",
                "entity": "application",
                "entity_key": "LOGIN_EVENT",
                "structure_path": ["Application family (1xx)"],
            },
        ),
        Document(
            page_content="### Other family (2xx)\nLOGOUT_EVENT",
            metadata={
                "doc_category": "entity-contract",
                "entity": "application",
                "entity_key": "LOGOUT_EVENT",
                "structure_path": ["Other family (2xx)"],
            },
        ),
    )
    monkeypatch.setattr(
        ChromaAccessRetriever,
        "_cached_authorized_corpus",
        lambda _self, _source_types: SimpleNamespace(documents=documents),
    )

    population = _retriever()._population_documents(
        "application", ("1xx",), ("PAGE",)
    )

    assert [item.metadata["entity_key"] for item in population] == ["LOGIN_EVENT"]
