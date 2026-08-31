import json
from pathlib import Path

from langchain_core.documents import Document

from app.workflow_nodes.answering import (
    _coverage_expected_identifiers,
    _expand_standalone_identifier_question,
    _explicit_entity_scope,
)
from app.workflow_support.inventory_intent import is_inventory_question


ROOT = Path(__file__).parents[1]
ENTITIES = ("pos", "bot", "iot", "fabric")
ANCHORED = [Document(page_content="payload", metadata={"identifier_anchor": True})]
POPULATION = [
    Document(page_content=identifier, metadata={"entity_key": identifier})
    for identifier in ("POS_LOGIN", "POS_LOGOUT", "POS_EXTRACT_CASH")
]


def _groups() -> dict[str, list[dict[str, object]]]:
    rows = json.loads(
        (ROOT / "evaluation" / "paraphrase_groups.json").read_text(encoding="utf-8")
    )
    groups: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        groups.setdefault(str(row["paraphrase_group"]), []).append(row)
    return groups


def _classification(question: str) -> tuple[bool, str, bool, int]:
    expanded = _expand_standalone_identifier_question(question, ANCHORED)
    return (
        is_inventory_question(question),
        _explicit_entity_scope(question, ENTITIES),
        expanded != question,
        len(_coverage_expected_identifiers(question, POPULATION)),
    )


def test_every_paraphrase_group_has_one_routing_class() -> None:
    groups = _groups()

    assert {name: len(rows) for name, rows in groups.items()} == {
        "named_member": 5,
        "pos_event_inventory": 5,
        "entity_behavior": 5,
        "cross_source": 5,
    }
    for name, rows in groups.items():
        signatures = {_classification(str(row["question"])) for row in rows}
        assert len(signatures) == 1, f"{name} diverged: {signatures}"

    assert _classification("what events does POS use?")[1] == "pos"
