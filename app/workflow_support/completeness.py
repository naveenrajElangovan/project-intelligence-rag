from __future__ import annotations

import json
import logging
import re

from langchain_core.documents import Document

from app.workflow_support.query_analysis import (
    _exact_feature_title_match,
    _feature_title_anchor,
    _normalized_words,
)


LOGGER = logging.getLogger("project_intelligence.rag.stages")

def _answer_requirements(
    question: str, entities: tuple[str, ...] = ()
) -> tuple[str, ...]:
    lowered = question.casefold()
    requirements: list[str] = []
    asks_files = bool(re.search(r"\b(files?|archivos?)\b", lowered))
    asks_lines = bool(re.search(r"\b(lines?|líneas?)\b", lowered))
    if asks_files and asks_lines:
        requirements.extend(("count:files", "count:lines"))

    enumerated = re.search(
        r"\bwhich\s+([a-z][a-z\s,-]*?(?:,|\band\b)[a-z\s,-]+?)\s+screen\s+types?\b",
        lowered,
    )
    enumerated_values: list[str] = []
    if enumerated:
        enumerated_values.extend(
            value.strip()
            for value in re.split(r"\s*(?:,|\band\b)\s*", enumerated.group(1))
            if value.strip()
        )
    if "screen" in lowered:
        flow_list = re.search(
            r"\b([a-z]+)\s*,\s*([a-z]+)\s*,?\s*(?:and|y)\s+([a-z]+)\s+flows?\b",
            lowered,
        )
        if flow_list:
            enumerated_values.extend(flow_list.groups())
    for value in enumerated_values:
        words = _normalized_words(value)
        if len(words) == 1 and words[0] not in {"the", "a", "an"}:
            requirements.append(f"term:{words[0]}")

    if _code_output_requested(question):
        requirements.append("code:implementation")

    entity_pattern = "|".join(re.escape(entity) for entity in entities)
    boundary = rf"\s+in\s+(?:{entity_pattern})\b" if entity_pattern else r"(?!)"
    listed_for = re.search(
        rf"\blisted\s+for\s+(?:the\s+)?(.+?)(?:{boundary}|\?|$)", lowered
    )
    if (
        listed_for
        and not (
            entities
            and re.match(rf"(?:{entity_pattern})\b", listed_for.group(1))
        )
        and re.search(r",|\band\b|\by\b", listed_for.group(1))
    ):
        requested_items = [
            value.strip(" -")
            for value in re.split(r"\s*(?:,|\band\b|\by\b)\s*", listed_for.group(1))
            if value.strip(" -")
        ]
        for item in requested_items:
            words = tuple(
                _singular_key(word)
                for word in _normalized_words(item)
                if word not in {"the", "a", "an"}
            )
            if 2 <= len(words) <= 4:
                requirements.append("identifier:" + "+".join(words))
    return tuple(dict.fromkeys(requirements))


def _missing_answer_requirements(
    question: str, answer: str, entities: tuple[str, ...] = ()
) -> tuple[str, ...]:
    requirements = _answer_requirements(question, entities)
    lowered = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", answer).casefold()
    missing: list[str] = []
    for requirement in requirements:
        if requirement == "count:files":
            present = bool(
                re.search(r"\b\d[\d,.]*\s+(?:kotlin\s+)?(?:source\s+)?files?\b", lowered)
                or re.search(r"\b\d[\d,.]*\s+archivos?(?:\s+fuente)?(?:\s+kotlin)?\b", lowered)
            )
        elif requirement == "count:lines":
            present = bool(
                re.search(r"\b\d[\d,.]*\s+(?:nonblank\s+)?(?:kotlin\s+)?lines?\b", lowered)
                or re.search(r"\b\d[\d,.]*\s+líneas?(?:\s+kotlin)?(?:\s+no\s+vacías)?\b", lowered)
            )
        elif requirement == "code:implementation":
            present = _code_answer_complete(question, answer)
        else:
            term = requirement.split(":", 1)[1]
            present = _text_satisfies_identifier_requirement(answer, requirement, term)
        if not present:
            missing.append(requirement)
    return tuple(missing)


def _completeness_repair_query(
    question: str,
    documents: list[Document],
    missing: tuple[str, ...],
) -> str:
    anchor = next(
        (
            _feature_title_anchor(
                str(document.metadata.get("title") or ""),
                str(document.metadata.get("entity") or ""),
            )
            for document in documents
            if _exact_feature_title_match(question, document)
        ),
        (),
    )
    anchor_text = " ".join(
        word.upper() if index == 0 else word
        for index, word in enumerate(anchor)
    )
    for value in dict.fromkeys(missing):
        if ":" not in value:
            LOGGER.warning(
                json.dumps(
                    {
                        "event": "rag_malformed_requirement",
                        "reason_code": "MALFORMED_REQUIREMENT",
                        "value": value,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
    terms = [
        value.split(":", 1)[1].replace("+", " ")
        if ":" in value
        else value.replace("+", " ")
        for value in missing
    ]
    if "code:implementation" in missing:
        terms.extend(("complete function bodies", "implementation code"))
    query = " ".join(value for value in (anchor_text, *terms) if value).strip()
    return query or question


def _include_repair_evidence(
    ranked: list[Document],
    candidates: list[Document],
    requirements: tuple[str, ...],
    *,
    top_n: int,
) -> list[Document]:
    """Pin at most one direct match per missing item after the bounded repair."""

    if not requirements:
        return ranked
    selected = list(ranked)
    selected_ids = {str(document.metadata.get("chunk_id") or id(document)) for document in selected}
    for requirement in requirements:
        term = requirement.split(":", 1)[1]
        match = next(
            (
                document
                for document in candidates
                if str(document.metadata.get("chunk_id") or id(document)) not in selected_ids
                and _document_satisfies_requirement(document, requirement, term)
            ),
            None,
        )
        if match is None:
            continue
        match.metadata["completeness_repair_evidence"] = True
        match.metadata["rerank_score"] = float(match.metadata.get("rerank_score") or 0)
        selected.append(match)
        selected_ids.add(str(match.metadata.get("chunk_id") or id(match)))
        if len(selected) >= top_n:
            break
    return selected[:top_n]


def _merge_ranked_documents(
    ranked: list[Document], prior: list[Document], *, top_n: int
) -> list[Document]:
    selected = list(ranked)
    selected_ids = {str(document.metadata.get("chunk_id") or id(document)) for document in selected}
    for document in prior:
        identity = str(document.metadata.get("chunk_id") or id(document))
        if identity not in selected_ids:
            selected.append(document)
            selected_ids.add(identity)
        if len(selected) >= top_n:
            break
    return selected[:top_n]


def _document_satisfies_requirement(
    document: Document, requirement: str, term: str
) -> bool:
    content = document.page_content
    lowered = content.casefold()
    if requirement.startswith(("term:", "identifier:")):
        return _text_satisfies_identifier_requirement(content, requirement, term)
    if requirement == "code:implementation":
        return _contains_implementation_code(content)
    if requirement == "count:files":
        return bool(re.search(r"\b\d[\d,.]*\s+.*?\b(?:files?|archivos?)\b", lowered))
    if requirement == "count:lines":
        return bool(re.search(r"\b\d[\d,.]*\s+.*?\b(?:lines?|líneas?)\b", lowered))
    return False


def _code_output_requested(question: str) -> bool:
    """Recognize an explicit request to display code, not a request about behavior."""

    normalized = " ".join(_normalized_words(question))
    if re.search(r"\b(?:which|what)\s+(?:source\s+)?files?\b|\bwhere\b", normalized):
        return False
    action = re.search(
        r"\b(?:show|give|provide|write|generate|display|include|share|return|"
        r"muestra|dame|proporciona|escribe|genera|incluye|comparte)\b",
        normalized,
    )
    # A request for “important functions” means an inventory/explanation, not
    # full source. Require an explicit code/source/implementation artifact (or
    # “function bodies”) before enforcing fenced, complete implementation code.
    artifact = re.search(
        r"\b(?:code|source|implementation|codigo|fuente|implementacion|"
        r"function\s+bodies|method\s+bodies|cuerpo(?:s)?\s+de\s+funcion(?:es)?)\b",
        normalized,
    )
    return bool(action and artifact)


def _contains_implementation_code(value: str) -> bool:
    """Reject metadata/import-only chunks as implementation evidence."""

    without_imports = re.sub(
        r"(?m)^\s*(?:import\s+.+|from\s+\S+\s+import\s+.+|package\s+.+|using\s+.+)\s*$",
        "",
        value,
    )
    return bool(
        re.search(
            r"(?m)^\s*(?:"
            r"(?:public\s+|private\s+|protected\s+|internal\s+|open\s+|suspend\s+|async\s+)*"
            r"(?:fun|def|class|interface|object|function)\s+[A-Za-z_]\w*"
            r"|(?:const|let|var)\s+[A-Za-z_]\w*\s*=\s*(?:async\s*)?\([^)]*\)\s*=>"
            r")",
            without_imports,
        )
    )


def _code_answer_complete(question: str, answer: str) -> bool:
    """Require useful implementation code when the user explicitly asks to see code."""

    if not _code_output_requested(question):
        return True
    blocks = re.findall(r"```[^\n]*\n(.*?)```", answer, flags=re.DOTALL)
    if not blocks:
        return False
    code = "\n".join(blocks)
    if re.search(r"(?:\.\.\.|TODO|rest of (?:the )?code|implementation omitted)", code, re.I):
        return False
    return _contains_implementation_code(code)


def _singular_key(value: str) -> str:
    return value[:-1] if len(value) > 4 and value.endswith("s") else value


def _identifier_components(value: str) -> tuple[str, ...]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    words = list(_normalized_words(spaced))
    combined: list[str] = []
    index = 0
    while index < len(words):
        if index + 1 < len(words) and (words[index], words[index + 1]) == ("view", "model"):
            combined.append("viewmodel")
            index += 2
        else:
            combined.append(_singular_key(words[index]))
            index += 1
    return tuple(combined)


def _text_satisfies_identifier_requirement(text: str, requirement: str, term: str) -> bool:
    expected = tuple(term.split("+"))
    for identifier in re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", text):
        components = _identifier_components(identifier)
        if requirement.startswith("term:"):
            if expected[0] in components and "screen" in components:
                return True
        elif all(value in components for value in expected):
            return True
    return False


def _missing_evidence_requirements(
    requirements: tuple[str, ...], documents: list[Document]
) -> tuple[str, ...]:
    return tuple(
        requirement
        for requirement in requirements
        if not any(
            _document_satisfies_requirement(
                document,
                requirement,
                requirement.split(":", 1)[1],
            )
            for document in documents
        )
    )
