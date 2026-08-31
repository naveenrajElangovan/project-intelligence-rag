from app.llm import GroundedAnswer
from langchain_core.documents import Document
from app.workflow_support.deterministic_answers import _deterministic_structured_inventory_answer
from app.workflow_support.answer_structure import AnswerLineKind, classify_answer_lines
from app.workflow_support.citations import (
    _answer_without_source_markers,
    _citations_valid,
    _remove_unsupported_claims,
)


def _answer(text: str, citations: list[int] | None = None) -> GroundedAnswer:
    return GroundedAnswer(answer=text, citations=citations or [1])


def test_long_heading_does_not_require_a_citation() -> None:
    value = _answer(
        "### Payload fields for the close shift event\n"
        "The event closes the active shift [SOURCE 1]."
    )
    assert _citations_valid(value, 1)


def test_cited_table_rows_pass_and_one_uncited_row_fails() -> None:
    table = (
        "| Field | Type | Required | Description | Source |\n"
        "|---|---|---|---|---|\n"
        "| shiftId | string | yes | Shift identifier | [SOURCE 1] |\n"
        "| storeId | string | yes | Store identifier | [SOURCE 1] |\n"
        "| reason | string | no | Closing reason | [SOURCE 1] |"
    )
    assert _citations_valid(_answer(table), 1)
    assert not _citations_valid(_answer(table.replace(" | [SOURCE 1] |", " | |", 1)), 1)


def test_pruning_removes_only_an_unsupported_table_row() -> None:
    bad = "| storeId | string | yes | Store identifier | [SOURCE 1] |"
    value = _answer(
        "| Field | Type | Required | Description | Source |\n"
        "|---|---|---|---|---|\n"
        "| shiftId | string | yes | Shift identifier | [SOURCE 1] |\n"
        f"{bad}\n"
        "| reason | string | no | Closing reason | [SOURCE 1] |"
    )
    pruned, removed = _remove_unsupported_claims(value, [bad])
    assert removed == 1
    assert bad not in pruned.answer
    assert "| Field | Type | Required | Description | Source |" in pruned.answer
    assert "|---|---|---|---|---|" in pruned.answer
    assert _citations_valid(pruned, 1)


def test_pruning_all_rows_removes_empty_table_skeleton() -> None:
    row = "| shiftId | string | yes | Shift identifier | [SOURCE 1] |"
    value = _answer(
        "Before the table is documented [SOURCE 1].\n"
        "| Field | Type | Required | Description | Source |\n"
        "|---|---|---|---|---|\n"
        f"{row}"
    )
    pruned, removed = _remove_unsupported_claims(value, [row])
    assert removed == 1
    assert "Field | Type" not in pruned.answer
    assert "---" not in pruned.answer


def test_fenced_code_with_pipes_is_not_a_table_or_claim() -> None:
    text = (
        "The configuration example follows [SOURCE 1].\n"
        "```text\n"
        "| this prose has many words but is code |\n"
        "|---|\n"
        "```"
    )
    kinds = [line.kind for line in classify_answer_lines(text)]
    assert kinds[1:] == [AnswerLineKind.CODE] * 4
    assert _citations_valid(_answer(text), 1)


def test_source_column_is_hidden_from_visible_table() -> None:
    visible = _answer_without_source_markers(
        "| Field | Description | Source |\n"
        "|---|---|---|\n"
        "| shiftId | Shift identifier | [SOURCE 1] |"
    )
    assert visible == "| Field | Description |\n| --- | --- |\n| shiftId | Shift identifier |"


def test_structured_inventory_extracts_registry_and_payload_rows_without_a_model() -> None:
    documents = [
        Document(page_content="ORDER_CLOSE_EVENT | ORDER_CLOSE | 116 | 0.1 | publishes | consumes | wired"),
        Document(
            page_content=(
                "eventType = EventType.ORDER_CLOSE_EVENT\n"
                "payload = CloseOrderEvent(\n"
                "    eventType = EventType.ORDER_CLOSE_EVENT.eventName,\n"
                "    storeId = terminal.storeId,\n"
                "    amountCents = params.amount\n"
                ")"
            )
        ),
    ]

    answer = _deterministic_structured_inventory_answer(
        "Give every payload field for ORDER_CLOSE_EVENT", documents, "en"
    )

    assert answer is not None
    assert "| Field | Type | Required | Description | Source |" in answer.answer
    assert "| `storeId` |" in answer.answer
    assert "`storeId = terminal.storeId`" in answer.answer
    assert _citations_valid(answer, 2)
