from langchain_core.documents import Document

from app.workflow_nodes.retrieval import (
    _scope_candidates_to_planned_types,
    _strong_lexical_anchors,
)


def _document(source_type: str) -> Document:
    return Document(page_content=source_type, metadata={"source_type": source_type})


def test_federated_candidates_are_bounded_by_the_planned_evidence_types() -> None:
    candidates = [_document("PAGE"), _document("CODE"), _document("ISSUE")]

    scoped = _scope_candidates_to_planned_types(candidates, ("PAGE", "CODE"))

    assert [item.metadata["source_type"] for item in scoped] == ["PAGE", "CODE"]


def test_jira_only_plan_cannot_leak_documentation_or_code() -> None:
    candidates = [_document("PAGE"), _document("ISSUE"), _document("CODE")]

    scoped = _scope_candidates_to_planned_types(candidates, ("ISSUE",))

    assert [item.metadata["source_type"] for item in scoped] == ["ISSUE"]


def test_empty_planned_scope_preserves_legacy_mixed_retrieval() -> None:
    candidates = [_document("PAGE"), _document("ISSUE")]

    assert _scope_candidates_to_planned_types(candidates, ()) == candidates


def test_typed_out_of_scope_pool_becomes_empty_instead_of_leaking() -> None:
    candidates = [_document("ISSUE")]

    assert _scope_candidates_to_planned_types(candidates, ("PAGE", "CODE")) == []


def test_metadata_free_legacy_retriever_remains_compatible() -> None:
    candidates = [Document(page_content="legacy", metadata={})]

    assert _scope_candidates_to_planned_types(candidates, ("PAGE",)) == candidates


def test_business_terms_survive_semantic_reranking_as_literal_anchors() -> None:
    exact = Document(
        page_content="The open-drawer action controls the cash drawer through the printer.",
        metadata={"source_type": "PAGE", "lexical_score": 1.0},
    )
    unrelated = Document(
        page_content="The payment workflow closes a sale.",
        metadata={"source_type": "PAGE", "lexical_score": 0.1},
    )

    assert _strong_lexical_anchors("What is the cash drawer in T2.0?", [unrelated, exact]) == [exact]


def test_developer_and_spanish_terms_use_the_same_literal_anchor_rule() -> None:
    developer = _document("CODE")
    developer.page_content = "Checkpoint recovery resumes from the committed cursor."
    spanish = _document("PAGE")
    spanish.page_content = "El cajón de efectivo se abre mediante la impresora."

    assert _strong_lexical_anchors("How does checkpoint recovery work?", [developer]) == [developer]
    assert _strong_lexical_anchors("¿Cómo funciona el cajón de efectivo?", [spanish]) == [spanish]


def test_weak_single_misspelling_does_not_create_a_literal_anchor() -> None:
    assert _strong_lexical_anchors(
        "What is memoy here?", [_document("PAGE")]
    ) == []


def test_prose_literal_anchor_wins_over_an_equivalent_table_anchor() -> None:
    table = Document(
        page_content="| F8 | Open cash drawer | Home |",
        metadata={"source_type": "PAGE", "lexical_score": 10.0},
    )
    prose = Document(
        page_content="The cash drawer opens through the printer integration.",
        metadata={"source_type": "PAGE", "lexical_score": 1.0},
    )

    assert _strong_lexical_anchors(
        "What is the cash drawer?", [table, prose], limit=1
    ) == [prose]
