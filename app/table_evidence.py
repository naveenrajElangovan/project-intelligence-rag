"""Rewrite table-shaped evidence as sentence-shaped evidence for scoring.

The cross-encoder that reranks candidates and verifies grounding
(``bge-reranker-v2-m3``) was trained on query/passage pairs of running text. A
Markdown pipe row carries its meaning positionally: the header two lines above
tells you what the third cell means, and the model has no reliable way to
recover that association. A claim that faithfully restates a table row therefore
scores far below an equally faithful claim restating a prose sentence, and
grounding rejected correct answers whenever the supporting evidence happened to
be a table.

The fix is to make the evidence look like what the model was trained on: one
sentence per row, every cell paired with its own header. This runs only on the
scoring path. The generation prompt keeps the original table, so answers can
still reproduce it verbatim.
"""

from __future__ import annotations

import re

# Two cells is the minimum that can carry a header/value relationship. Below it,
# a line containing a pipe is far more likely to be prose or a code fragment.
_MINIMUM_CELLS = 2
# Past this width a linearised row is long enough to crowd the cross-encoder's
# 512-position window, which costs more than the header association gains.
_MAXIMUM_CELLS = 12
# A single row cannot be distinguished from prose; a header plus one body row is
# the smallest thing that is unambiguously a table.
_MINIMUM_ROWS = 2

_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")
_EMPTY_CELLS = {"", "-", "--", "—", "n/a", "N/A"}
_FENCE = re.compile(r"^\s*(`{3,}|~{3,})")


def normalize_table_dialect(value: str) -> str:
    """Canonicalize separatorless pipe-table runs at the retrieval boundary.

    Confluence HTML ingestion historically stored rows as ``A | B | C`` while
    document ingestion stored Markdown tables. Structural consumers deliberately
    understand only the latter. This adapter gives already-indexed page evidence
    that canonical shape without teaching every downstream parser a second
    dialect.
    """

    lines = value.splitlines()
    output: list[str] = []
    index = 0
    fence: str | None = None
    while index < len(lines):
        line = lines[index]
        fence_match = _FENCE.match(line)
        if fence is not None:
            output.append(line)
            if fence_match and fence_match.group(1)[0] == fence:
                fence = None
            index += 1
            continue
        if fence_match:
            fence = fence_match.group(1)[0]
            output.append(line)
            index += 1
            continue
        if line.count("|") < 2:
            output.append(line)
            index += 1
            continue

        end = index
        while end < len(lines) and lines[end].count("|") >= 2:
            end += 1
        run = lines[index:end]
        if len(run) < 2 or (
            len(run) >= 2
            and _is_row(run[0])
            and _SEPARATOR.fullmatch(run[1]) is not None
        ):
            output.extend(run)
            index = end
            continue

        canonical_rows = [_canonical_pipe_row(row) for row in run]
        separator = "| " + " | ".join("---" for _ in _cells(canonical_rows[0])) + " |"
        output.extend([canonical_rows[0], separator, *canonical_rows[1:]])
        index = end

    normalized = "\n".join(output)
    return normalized + ("\n" if value.endswith("\n") and normalized else "")


def _canonical_pipe_row(line: str) -> str:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return "| " + " | ".join(cells) + " |"


def contains_table(value: str) -> bool:
    """Report whether *value* holds at least one Markdown pipe table."""

    lines = value.splitlines()
    index = 0
    while index < len(lines):
        rows, next_index = _table_block(lines, index)
        if rows is not None:
            return True
        index = next_index if next_index > index else index + 1
    return False


def linearize_tables(value: str) -> str:
    """Return *value* with every Markdown pipe table rewritten as prose rows."""

    lines = value.splitlines()
    output: list[str] = []
    index = 0
    while index < len(lines):
        rows, next_index = _table_block(lines, index)
        if rows is None:
            output.append(lines[index])
            index += 1
            continue
        output.extend(_linearized(rows))
        index = next_index
    return "\n".join(output)


def linearize_table_row(header: str, row: str) -> str:
    """Linearize one generated row with its header using the evidence machinery."""

    rows = [_cells(header), _cells(row)]
    linearized = _linearized(rows)
    return linearized[0] if linearized else row


def literal_table_row_evidence(header: str, row: str, evidence: str) -> str | None:
    """Shape exact quoted cells as row evidence; reject any generated prose cell."""

    cells = _cells(row)
    for cell in cells:
        value = re.sub(r"\s*\[SOURCE \d+\]", "", cell).strip()
        if value in _EMPTY_CELLS:
            continue
        match = re.fullmatch(r"`([^`]+)`", value)
        if match is None or match.group(1) not in evidence:
            return None
    return linearize_table_row(header, row)


def _table_block(lines: list[str], start: int) -> tuple[list[list[str]] | None, int]:
    """Collect the run of pipe rows beginning at *start*, if one begins there."""

    rows: list[list[str]] = []
    index = start
    while index < len(lines):
        line = lines[index]
        if not _is_row(line):
            break
        if _SEPARATOR.match(line):
            index += 1
            continue
        cells = _cells(line)
        if not _MINIMUM_CELLS <= len(cells) <= _MAXIMUM_CELLS:
            break
        rows.append(cells)
        index += 1
    if len(rows) < _MINIMUM_ROWS:
        return None, start
    return rows, index


def _is_row(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.count("|") >= 2


def _cells(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _linearized(rows: list[list[str]]) -> list[str]:
    headers = [
        header if header not in _EMPTY_CELLS else f"column {position}"
        for position, header in enumerate(rows[0], start=1)
    ]
    sentences: list[str] = []
    for row in rows[1:]:
        labelled = [
            f"{headers[position]}: {cell}"
            for position, cell in enumerate(row)
            if position < len(headers) and cell not in _EMPTY_CELLS
        ]
        if not labelled:
            continue
        # The first cell is the row's subject. Leading with it bare, then giving
        # the remaining cells their header labels, reads closest to a sentence.
        subject = row[0].strip()
        if len(labelled) > 1 and subject not in _EMPTY_CELLS:
            sentences.append(f"{subject} — " + "; ".join(labelled[1:]) + ".")
        else:
            sentences.append("; ".join(labelled) + ".")
    return sentences
