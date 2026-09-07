"""Stage telemetry must not carry corpus content out of the process.

SECURITY_AND_PRIVACY requires content to be kept out of observability at the
source, and this list reaches Loki and Phoenix. A Confluence page title and a
repository path are content: the live logs contained
"Tiendas 3B ... Event and Integration Contract" and
"tools/expense_flow_validation/run.py" before this was fixed.
"""

import json

from langchain_core.documents import Document

from app.workflow_nodes.answering import (
    _content_digest,
    _scope_documents_to_entity,
)


SECRET_TITLE = "Quarterly Margin Review for Leche Suppliers"


def _excluded() -> list[dict[str, object]]:
    documents = [
        Document(
            page_content="irrelevant",
            metadata={"title": SECRET_TITLE, "entity": "pos", "path": "tools/run.py"},
        )
    ]

    _scoped, excluded, records, _flag = _scope_documents_to_entity(documents, "bot")

    assert excluded == 1
    return records


def test_no_document_title_reaches_telemetry() -> None:
    serialized = json.dumps(_excluded())

    assert SECRET_TITLE not in serialized
    assert "Leche" not in serialized
    assert "tools/run.py" not in serialized


def test_the_diagnostic_value_is_preserved() -> None:
    record = _excluded()[0]

    assert record["exclusion_reason"] == "not_in_entities"
    assert record["resolved_entities"] == ["pos"]
    assert len(str(record["title_digest"])) == 12


def test_the_digest_is_stable_so_repeats_still_correlate() -> None:
    assert _content_digest(SECRET_TITLE) == _content_digest(SECRET_TITLE)
    assert _content_digest("a different title") != _content_digest(SECRET_TITLE)


def test_a_missing_title_produces_no_digest() -> None:
    assert _content_digest(None) == ""
    assert _content_digest("   ") == ""
