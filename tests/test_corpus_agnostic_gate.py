from pathlib import Path

from langchain_core.documents import Document

from app.vocabulary import CorpusVocabulary
from app.workflow_support.query_analysis import (
    _entity_overview_entity,
    _feature_inventory_entity,
    _inventory_documents,
)


def test_application_code_contains_no_fixture_entity_literals() -> None:
    app = Path(__file__).parents[1] / "app"
    offenders = []
    for path in app.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for entity in ("POS", "BOT"):
            if entity in text:
                offenders.append(f"{path.relative_to(app)}:{entity}")
    assert offenders == []


def test_second_project_entities_and_title_conventions_need_no_code_change() -> None:
    vocabulary = CorpusVocabulary(
        entities=("atlas", "nova"),
        doc_categories=("feature-page", "workflow"),
        source_types=("PAGE", "CODE"),
        code_extensions=(".go", ".rs"),
    )
    documents = [
        Document(
            page_content="Handles route optimization.",
            metadata={
                "title": "Routing and dispatch",
                "entity": "atlas",
                "doc_category": "feature-page",
            },
        ),
        Document(
            page_content="Maintains settlement ledgers.",
            metadata={
                "title": "Ledger operations",
                "entity": "nova",
                "doc_category": "feature-page",
            },
        ),
    ]

    assert _entity_overview_entity("Tell me about Atlas", vocabulary.entities) == "atlas"
    assert (
        _feature_inventory_entity("List all Atlas features", vocabulary.entities)
        == "atlas"
    )
    assert _inventory_documents(documents, "atlas")
    assert len(vocabulary.entities) == 2
