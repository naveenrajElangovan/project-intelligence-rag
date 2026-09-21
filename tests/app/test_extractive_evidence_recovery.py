from langchain_core.documents import Document

from app.workflow_support.deterministic_answers import (
    _deterministic_extractive_answer,
    _has_strong_evidence_anchor,
)


def _document(text: str, source_type: str = "PAGE") -> Document:
    return Document(
        page_content=text,
        metadata={"source_type": source_type, "rerank_score": 0.2},
    )


def test_store_concept_recovers_complete_evidence_sentences() -> None:
    answer = _deterministic_extractive_answer(
        "What is the cash drawer in T2.0?",
        [
            _document(
                "Retrieval terms: F8, open drawer, cash drawer. "
                "The open-drawer action is a sale shortcut and desktop menu operation. "
                "It routes through the printer integration for drawer control."
            )
        ],
        "en",
    )

    assert answer is not None
    assert "cash drawer" in answer.answer
    assert "sale shortcut" in answer.answer
    assert answer.citations == [1]


def test_developer_concept_uses_the_same_provider_neutral_rule() -> None:
    answer = _deterministic_extractive_answer(
        "How does checkpoint recovery work?",
        [
            _document(
                "Checkpoint recovery resumes from the last committed source cursor. "
                "A failed write leaves the prior indexed version available for retry."
            )
        ],
        "en",
    )

    assert answer is not None
    assert "source cursor" in answer.answer


def test_spanish_concept_uses_the_same_rule() -> None:
    answer = _deterministic_extractive_answer(
        "¿Cómo funciona el cajón de efectivo?",
        [
            _document(
                "El cajón de efectivo requiere autorización del responsable de caja. "
                "La apertura se solicita mediante la integración con la impresora."
            )
        ],
        "es",
    )

    assert answer is not None
    assert "¿Cómo funciona el cajón de efectivo?" in answer.answer
    assert "autorización" in answer.answer


def test_unrelated_or_misspelled_question_does_not_extract_a_false_answer() -> None:
    answer = _deterministic_extractive_answer(
        "What is memoy here?",
        [_document("The cash drawer opens through the printer integration.")],
        "en",
    )

    assert answer is None
    assert not _has_strong_evidence_anchor(
        "What is memoy here?",
        [_document("The application manages an Android instrument cluster.")],
    )


def test_store_developer_jira_and_spanish_subjects_share_the_anchor_rule() -> None:
    cases = (
        ("What is the cash drawer?", "Cash drawer operations use printer integration."),
        ("How does checkpoint recovery work?", "Checkpoint recovery resumes a committed cursor."),
        ("What is the status of T0-122?", "T0-122 currently has status To Do."),
        ("¿Cómo funciona el cajón de efectivo?", "El cajón de efectivo usa la impresora."),
    )

    for question, evidence in cases:
        assert _has_strong_evidence_anchor(question, [_document(evidence)])


def test_jira_and_code_evidence_are_supported_without_domain_branches() -> None:
    jira = _deterministic_extractive_answer(
        "Which issue is blocked by printer authorization?",
        [_document("Issue T0-43 is blocked by printer authorization.", "ISSUE")],
        "en",
    )
    code = _deterministic_extractive_answer(
        "Where is drawer control implemented?",
        [_document("Drawer control is implemented by PrinterService.openDrawer().", "CODE")],
        "en",
    )

    assert jira is not None
    assert code is not None


def test_prose_definition_wins_over_a_compact_matching_table_row() -> None:
    answer = _deterministic_extractive_answer(
        "What is the cash drawer?",
        [
            _document("| F8 | Open cash drawer | Home screen |"),
            _document(
                "The cash drawer is controlled through the printer integration. "
                "Opening it requires the responsible cashier's authorization."
            ),
        ],
        "en",
    )

    assert answer is not None
    assert "printer integration" in answer.answer
    assert "| F8 |" not in answer.answer
