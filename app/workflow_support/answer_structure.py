from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class AnswerLineKind(StrEnum):
    HEADING = "HEADING"
    TABLE_SEPARATOR = "TABLE_SEPARATOR"
    TABLE_HEADER = "TABLE_HEADER"
    TABLE_ROW = "TABLE_ROW"
    CODE = "CODE"
    LIST_ITEM = "LIST_ITEM"
    PROSE = "PROSE"


@dataclass(frozen=True, slots=True)
class AnswerLine:
    text: str
    kind: AnswerLineKind
    table_header: str = ""


@dataclass(frozen=True, slots=True)
class AnswerClaim:
    text: str
    kind: AnswerLineKind
    table_header: str = ""


_HEADING = re.compile(r"^#{1,6}\s")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def classify_answer_lines(answer: str) -> list[AnswerLine]:
    """Classify Markdown lines while treating fenced content as opaque code."""

    raw = answer.splitlines()
    code_indexes: set[int] = set()
    inside_fence = False
    for index, line in enumerate(raw):
        if line.lstrip().startswith("```"):
            code_indexes.add(index)
            inside_fence = not inside_fence
        elif inside_fence:
            code_indexes.add(index)

    table_headers: dict[int, str] = {}
    table_rows: dict[int, str] = {}
    index = 0
    while index + 1 < len(raw):
        if index in code_indexes or index + 1 in code_indexes:
            index += 1
            continue
        if _is_pipe_row(raw[index]) and _TABLE_SEPARATOR.fullmatch(raw[index + 1]):
            header = raw[index]
            table_headers[index] = header
            cursor = index + 2
            while cursor < len(raw) and cursor not in code_indexes and _is_pipe_row(raw[cursor]):
                table_rows[cursor] = header
                cursor += 1
            index = cursor
            continue
        index += 1

    classified: list[AnswerLine] = []
    for index, line in enumerate(raw):
        if index in code_indexes:
            kind = AnswerLineKind.CODE
        elif index in table_headers:
            kind = AnswerLineKind.TABLE_HEADER
        elif _TABLE_SEPARATOR.fullmatch(line):
            kind = AnswerLineKind.TABLE_SEPARATOR
        elif index in table_rows:
            kind = AnswerLineKind.TABLE_ROW
        elif _HEADING.match(line):
            kind = AnswerLineKind.HEADING
        elif _LIST_ITEM.match(line):
            kind = AnswerLineKind.LIST_ITEM
        else:
            kind = AnswerLineKind.PROSE
        classified.append(AnswerLine(line, kind, table_rows.get(index, "")))
    return classified


def material_claims(answer: str) -> list[AnswerClaim]:
    claims: list[AnswerClaim] = []
    for line in classify_answer_lines(answer):
        if line.kind in {AnswerLineKind.TABLE_ROW, AnswerLineKind.LIST_ITEM}:
            claims.append(AnswerClaim(line.text.strip(), line.kind, line.table_header))
        elif line.kind is AnswerLineKind.PROSE:
            claims.extend(
                AnswerClaim(sentence.strip(), line.kind)
                for sentence in _SENTENCE_SPLIT.split(line.text.strip())
                if len(re.findall(r"\w+", sentence)) >= 4
            )
    return claims


def answer_shape_metrics(answer: str, *, claims_removed: int = 0) -> dict[str, int | str]:
    lines = classify_answer_lines(answer)
    kinds = {line.kind for line in lines if line.text.strip()}
    sections = [
        label
        for label, kind in (
            ("prose", AnswerLineKind.PROSE),
            ("headings", AnswerLineKind.HEADING),
            ("tables", AnswerLineKind.TABLE_HEADER),
            ("lists", AnswerLineKind.LIST_ITEM),
            ("code", AnswerLineKind.CODE),
        )
        if kind in kinds
    ]
    return {
        "answer_sentence_count": len(material_claims(answer)),
        "answer_table_count": sum(line.kind is AnswerLineKind.TABLE_HEADER for line in lines),
        "answer_table_rows": sum(line.kind is AnswerLineKind.TABLE_ROW for line in lines),
        "answer_list_items": sum(line.kind is AnswerLineKind.LIST_ITEM for line in lines),
        "sections_present": ",".join(sections) or "none",
        "claims_removed": max(0, claims_removed),
    }


def prune_unsupported_claims(answer: str, unsupported_claims: set[str]) -> tuple[str, int]:
    """Remove only rejected claims while preserving valid Markdown structure."""

    output: list[str] = []
    removed = 0
    for line in classify_answer_lines(answer):
        if line.kind in {AnswerLineKind.TABLE_ROW, AnswerLineKind.LIST_ITEM}:
            if _normalized(line.text) in unsupported_claims:
                removed += 1
            else:
                output.append(line.text)
            continue
        if line.kind is AnswerLineKind.PROSE:
            sentences = _SENTENCE_SPLIT.split(line.text.strip()) if line.text.strip() else []
            retained: list[str] = []
            for sentence in sentences:
                if _normalized(sentence) in unsupported_claims:
                    removed += 1
                else:
                    retained.append(sentence.strip())
            output.append(" ".join(retained) if sentences else line.text)
            continue
        output.append(line.text)

    cleaned: list[str] = []
    index = 0
    while index < len(output):
        if index + 1 < len(output) and _is_pipe_row(output[index]) and _TABLE_SEPARATOR.fullmatch(output[index + 1]):
            cursor = index + 2
            while cursor < len(output) and _is_pipe_row(output[cursor]):
                cursor += 1
            if cursor == index + 2:
                index += 2
                continue
        cleaned.append(output[index])
        index += 1
    return "\n".join(cleaned).strip(), removed


def _is_pipe_row(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and not _TABLE_SEPARATOR.fullmatch(stripped)


def _normalized(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()
