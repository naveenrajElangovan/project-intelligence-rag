from app.reranking import sanitize_evidence, scoring_evidence
from app.table_evidence import (
    contains_table,
    linearize_tables,
    literal_table_row_evidence,
    normalize_table_dialect,
)
from app.workflow_support.answer_structure import answer_shape_metrics, classify_answer_lines

EVENT_TABLE = """### `POS_CLOSE_SHIFT` — id 104, version 0.4

`ShiftSummary` is the end-of-shift reconciliation record:

| Member | Wire name | Contents |
|---|---|---|
| ticketsCount | `tickets_count` | Int |
| totalCredits | `total_credits` | `amount_cents`, `overage_amount_cents` |

Every member defaults.
"""


def test_pipe_table_becomes_one_sentence_per_row():
    result = linearize_tables(EVENT_TABLE)
    assert "ticketsCount — Wire name: `tickets_count`; Contents: Int." in result
    assert (
        "totalCredits — Wire name: `total_credits`; Contents: `amount_cents`, "
        "`overage_amount_cents`." in result
    )
    # The separator row must not survive as a sentence.
    assert "---" not in result


def test_surrounding_prose_is_untouched():
    result = linearize_tables(EVENT_TABLE)
    assert "### `POS_CLOSE_SHIFT` — id 104, version 0.4" in result
    assert "Every member defaults." in result


def test_every_cell_value_survives_linearization():
    result = linearize_tables(EVENT_TABLE)
    for value in ("tickets_count", "total_credits", "amount_cents", "overage_amount_cents", "Int"):
        assert value in result


def test_prose_containing_a_pipe_is_not_treated_as_a_table():
    prose = "The route is | separated in the log line, which is confusing.\nNothing else."
    assert linearize_tables(prose) == prose
    assert contains_table(prose) is False


def test_single_pipe_row_is_left_alone():
    single = "| Member | Wire name |"
    assert linearize_tables(single) == single
    assert contains_table(single) is False


def test_table_without_a_separator_row_still_linearizes():
    table = "| Field | Type |\n| shiftId | String |\n| folio | String |"
    result = linearize_tables(table)
    assert "shiftId — Type: String." in result
    assert "folio — Type: String." in result


def test_empty_cells_are_dropped_rather_than_labelled():
    table = "| Field | Type | Notes |\n|---|---|---|\n| folio | String | - |"
    assert linearize_tables(table) == "folio — Type: String."


def test_ragged_row_shorter_than_the_header_is_kept():
    table = "| Field | Type | Notes |\n|---|---|---|\n| folio | String |"
    assert linearize_tables(table) == "folio — Type: String."


def test_very_wide_rows_are_left_as_written():
    header = "| " + " | ".join(f"c{index}" for index in range(20)) + " |"
    body = "| " + " | ".join(f"v{index}" for index in range(20)) + " |"
    table = f"{header}\n{body}"
    assert linearize_tables(table) == table


def test_missing_header_cell_gets_a_positional_label():
    table = "| Field |  |\n|---|---|\n| folio | String |"
    assert linearize_tables(table) == "folio — column 2: String."


def test_two_tables_in_one_chunk_are_both_rewritten():
    chunk = (
        "| A | B |\n|---|---|\n| a1 | b1 |\n\n"
        "Prose between.\n\n"
        "| C | D |\n|---|---|\n| c1 | d1 |\n"
    )
    result = linearize_tables(chunk)
    assert "a1 — B: b1." in result
    assert "c1 — D: d1." in result
    assert "Prose between." in result


def test_contains_table_detects_a_real_table():
    assert contains_table(EVENT_TABLE) is True


def test_page_and_document_table_shapes_are_equivalent_after_boundary_normalization():
    page = "Key | Action | Condition\nF1 | Close sale | main screen\nF6 | Check price | open shift"
    document = (
        "| Key | Action | Condition |\n"
        "| --- | --- | --- |\n"
        "| F1 | Close sale | main screen |\n"
        "| F6 | Check price | open shift |"
    )

    normalized_page = normalize_table_dialect(page)
    normalized_document = normalize_table_dialect(document)

    assert contains_table(normalized_page) == contains_table(normalized_document) is True
    assert linearize_tables(normalized_page) == linearize_tables(normalized_document)
    assert answer_shape_metrics(normalized_page) == answer_shape_metrics(normalized_document)
    assert classify_answer_lines(normalized_page) == classify_answer_lines(normalized_document)


def test_table_dialect_normalization_is_idempotent():
    page = "Key | Action\nF1 | Close sale"
    once = normalize_table_dialect(page)
    assert normalize_table_dialect(once) == once


def test_table_dialect_normalization_leaves_fenced_code_unchanged():
    fenced = "```text\nKey | Action\nF1 | Close sale\n```"
    assert normalize_table_dialect(fenced) == fenced


def test_single_pipe_delimited_line_remains_prose():
    line = "Key | Action | Condition"
    assert normalize_table_dialect(line) == line


def test_literal_row_evidence_accepts_only_exact_quoted_cells():
    header = "| Field | Description | Source |"
    exact = "| `storeId` | `storeId = terminal.storeId` | [SOURCE 1] |"
    prose = "| `storeId` | Store identifier | [SOURCE 1] |"
    evidence = "storeId = terminal.storeId"

    assert literal_table_row_evidence(header, exact, evidence) is not None
    assert literal_table_row_evidence(header, prose, evidence) is None


def test_scoring_evidence_can_be_switched_off():
    assert scoring_evidence(EVENT_TABLE, linearize_tables_enabled=False) == sanitize_evidence(
        EVENT_TABLE
    )
    assert scoring_evidence(EVENT_TABLE) != sanitize_evidence(EVENT_TABLE)


def test_scoring_evidence_still_strips_control_characters():
    assert "\x07" not in scoring_evidence("bell\x07here")
