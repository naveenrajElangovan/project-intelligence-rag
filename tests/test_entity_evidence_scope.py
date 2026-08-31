from langchain_core.documents import Document

from app.workflow_nodes.answering import (
    _explicit_entity_scope,
    _scope_documents_to_entity,
)


def test_explicit_entity_scope_accepts_only_corpus_vocabulary_members() -> None:
    entities = ("pos", "bot", "inventory")

    assert (
        _explicit_entity_scope("how can a user close the shift from POS?", entities)
        == "pos"
    )
    assert _explicit_entity_scope("what is the payload of the request?", entities) == ""
    assert _explicit_entity_scope("details about reconciliation", entities) == ""


def test_multi_entity_document_is_kept_when_it_contains_requested_entity() -> None:
    shared_registry = Document(
        page_content="Cross-application event registry",
        metadata={"title": "POS and BOT applications"},
    )

    scoped, excluded, diagnostics, scope_bypassed = _scope_documents_to_entity(
        [shared_registry], "pos"
    )

    assert scoped == [shared_registry]
    assert excluded == 0
    assert diagnostics == []
    assert scope_bypassed is False


def test_total_entity_mismatch_bypasses_scope_and_keeps_evidence() -> None:
    other_application = Document(
        page_content="Application-specific behavior",
        metadata={"entity_key": "bot"},
    )

    scoped, excluded, diagnostics, scope_bypassed = _scope_documents_to_entity(
        [other_application], "pos"
    )

    assert scoped == [other_application]
    assert excluded == 1
    assert diagnostics == [
        {
            "title": "",
            "resolved_entities": ["bot"],
            "exclusion_reason": "not_in_entities",
        }
    ]
    assert scope_bypassed is True


def test_entity_scope_still_excludes_mismatches_when_some_evidence_remains() -> None:
    matching = Document(
        page_content="POS-specific behavior",
        metadata={"entity_key": "pos"},
    )
    other_application = Document(
        page_content="BOT-specific behavior",
        metadata={"entity_key": "bot"},
    )

    scoped, excluded, diagnostics, scope_bypassed = _scope_documents_to_entity(
        [matching, other_application], "pos"
    )

    assert scoped == [matching]
    assert excluded == 1
    assert diagnostics == [
        {
            "title": "",
            "resolved_entities": ["bot"],
            "exclusion_reason": "not_in_entities",
        }
    ]
    assert scope_bypassed is False
