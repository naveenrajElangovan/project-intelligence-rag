from __future__ import annotations

import re

from app.llm import GroundedAnswer
from app.workflow_support.answer_structure import material_claims, prune_unsupported_claims

def _citations_valid(value: GroundedAnswer, count: int) -> bool:
    if not value.citations or any(index < 1 or index > count for index in value.citations):
        return False
    mentioned = {int(number) for number in re.findall(r"\[SOURCE (\d+)\]", value.answer)}
    return set(value.citations) == mentioned and _all_material_sentences_cited(value.answer)


def _remove_unsupported_claims(
    value: GroundedAnswer, unsupported_claims: list[str]
) -> tuple[GroundedAnswer, int]:
    """Remove verifier-identified sentences without generating replacement facts."""

    unsupported = {_normalized_sentence(claim) for claim in unsupported_claims}
    answer, removed = prune_unsupported_claims(value.answer, unsupported)
    pruned = value.model_copy(update={"answer": answer})
    return _normalize_citations(pruned), removed


def _normalized_sentence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _material_sentence_count(answer: str) -> int:
    return len(material_claims(answer))


def _citation_failure_reason(value: GroundedAnswer, count: int) -> str:
    mentioned = {int(number) for number in re.findall(r"\[SOURCE (\d+)\]", value.answer)}
    if not mentioned:
        return "NO_MARKERS"
    if any(index < 1 or index > count for index in mentioned | set(value.citations)):
        return "OUT_OF_RANGE"
    if set(value.citations) != mentioned:
        return "MISMATCH"
    return "UNCITED_SENTENCE"


def _normalize_citations(value: GroundedAnswer) -> GroundedAnswer:
    """Mirror explicit answer markers into the structured citation field."""

    answer = re.sub(
        r"\[SOURCE\s+(\d+(?:\s*,\s*(?:SOURCE\s+)?\d+)+)\]",
        lambda match: " ".join(
            f"[SOURCE {number}]" for number in re.findall(r"\d+", match.group(1))
        ),
        value.answer,
        flags=re.IGNORECASE,
    )
    answer = re.sub(
        r"([.!?])\s*((?:\[SOURCE \d+\]\s*)+)",
        lambda match: " " + match.group(2).strip() + match.group(1),
        answer,
    )
    mentioned = list(
        dict.fromkeys(int(number) for number in re.findall(r"\[SOURCE (\d+)\]", answer))
    )
    if mentioned == value.citations and answer == value.answer:
        return value
    return value.model_copy(update={"answer": answer, "citations": mentioned})


def _answer_without_source_markers(answer: str) -> str:
    """Remove internal citation markers only after all guardrails have passed."""

    visible = _strip_table_source_columns(answer)
    visible = re.sub(r"\s*\[SOURCE\s+\d+\]", "", visible, flags=re.IGNORECASE)
    visible = re.sub(r"[ \t]+([.,;:!?])", r"\1", visible)
    visible = re.sub(r"[,;:]+(?=[.!?])", "", visible)
    visible = re.sub(r",{2,}", ",", visible)
    visible = re.sub(r"([.!?])(?:\s*\1)+", r"\1", visible)
    visible = re.sub(r"[ \t]{2,}", " ", visible)
    return visible.strip()


def _strip_table_source_columns(answer: str) -> str:
    """Hide an internal trailing Source column while retaining the table shape."""

    lines = answer.splitlines()
    output: list[str] = []
    index = 0
    separator = re.compile(r"^\s*\|?[\s:|-]*-{2,}[\s:|-]*\|?\s*$")
    while index < len(lines):
        if index + 1 < len(lines) and separator.fullmatch(lines[index + 1]):
            header = _pipe_cells(lines[index])
            if header and header[-1].strip().casefold() == "source":
                output.append(_pipe_row(header[:-1]))
                output.append(_pipe_row(_pipe_cells(lines[index + 1])[:-1]))
                index += 2
                while index < len(lines) and lines[index].strip().startswith("|"):
                    output.append(_pipe_row(_pipe_cells(lines[index])[:-1]))
                    index += 1
                continue
        output.append(lines[index])
        index += 1
    return "\n".join(output)


def _pipe_cells(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    return [cell.strip() for cell in stripped.split("|")] if "|" in line else []


def _pipe_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def drop_uncited_claims(
    value: GroundedAnswer, count: int
) -> tuple[GroundedAnswer, int]:
    """Remove only the claims that carry no citation, keeping the cited ones.

    A single uncited sentence used to discard the whole answer, so seven verified
    sentences were lost to fix one. Dropping just the offending claims keeps the
    citation guarantee intact -- every surviving claim still carries a marker, and
    grounding still judges each one -- while the cost of the failure falls on the
    sentence that caused it instead of on the answer.

    Returns the answer unchanged with a zero count when nothing can be salvaged,
    so the caller keeps its existing refusal path for a genuinely broken answer.
    """

    uncited = {
        _normalized_sentence(claim.text)
        for claim in material_claims(value.answer)
        if not re.search(r"\[SOURCE \d+\]", claim.text)
    }
    if not uncited:
        return value, 0
    answer, removed = prune_unsupported_claims(value.answer, uncited)
    if not removed:
        return value, 0
    pruned = _normalize_citations(value.model_copy(update={"answer": answer}))
    if not _citations_valid(pruned, count):
        return value, 0
    return pruned, removed


def _all_material_sentences_cited(answer: str) -> bool:
    claims = material_claims(answer)
    return bool(claims) and all(
        re.search(r"\[SOURCE \d+\]", claim.text) for claim in claims
    )


def _overview_style_repair_needed(question: str, answer: str) -> bool:
    """Detect audit or code-inventory output that a broad overview did not request."""

    if re.search(
        r"\b(?:count|counts|files?|lines?|symbols?|tests?|percentage|metrics?|status|maturity)\b",
        question,
        flags=re.IGNORECASE,
    ):
        return False
    claim_text = re.sub(r"\[SOURCE \d+\]", "", answer)
    return bool(
        re.search(r"(?<![\w.])\d+(?:[.,]\d+)*(?![\w.])", claim_text)
        or re.search(
            r"\b(?:implemented\s+by\s+the\s+following|files?\s+and\s+symbols?|"
            r"imports?\s+and\s+(?:classes|functions|symbols))\b",
            claim_text,
            flags=re.IGNORECASE,
        )
        or len(
            re.findall(
                r"\b(?:[a-zA-Z_]\w*\.){2,}[A-Za-z_]\w*\b",
                claim_text,
            )
        )
        >= 3
        or re.search(
            r"\b(?:draft|production-ready|maturity|lifecycle status)\b",
            claim_text,
            flags=re.IGNORECASE,
        )
    )
