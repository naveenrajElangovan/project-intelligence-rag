from __future__ import annotations

import re

from langchain_core.documents import Document

from app.llm import GroundedAnswer
from app.workflow_support.completeness import (
    _answer_requirements,
    _identifier_components,
    _singular_key,
)
from app.workflow_support.query_analysis import (
    _document_source_type,
    _normalized_words,
)

def _deterministic_identifier_answer(
    question: str, documents: list[Document], language: str
) -> GroundedAnswer | None:
    requirements = _answer_requirements(question)
    if len(requirements) < 2 or not all(
        requirement.startswith("identifier:") for requirement in requirements
    ):
        return None
    selected: list[str] = []
    citations: list[int] = []
    for requirement in requirements:
        expected = tuple(requirement.split(":", 1)[1].split("+"))
        matches: list[tuple[int, int, str, int]] = []
        for source_number, document in enumerate(documents, start=1):
            for identifier in re.findall(r"\b[A-Z][A-Za-z0-9_]{2,}\b", document.page_content):
                components = _identifier_components(identifier)
                if all(value in components for value in expected):
                    matches.append(
                        (len(components) - len(expected), len(identifier), identifier, source_number)
                    )
        if not matches:
            return None
        _extra, _length, identifier, source_number = min(matches)
        selected.append(identifier)
        citations.append(source_number)
    cited = list(dict.fromkeys(citations))
    names = (
        selected[0]
        if len(selected) == 1
        else ", ".join(selected[:-1]) + f", and {selected[-1]}"
    )
    prefix = "Los tipos solicitados son" if language == "es" else "The requested types are"
    markers = " ".join(f"[SOURCE {number}]" for number in cited)
    return GroundedAnswer(
        answer=f"{prefix} {names} {markers}.",
        citations=cited,
        missing_information=[],
    )


def _deterministic_structured_inventory_answer(
    question: str, documents: list[Document], language: str
) -> GroundedAnswer | None:
    """Render an exact event registry row and named payload assignments as a table."""

    identifiers = re.findall(r"\b[A-Z][A-Z0-9_]{4,}\b", question)
    if not identifiers:
        return None
    target = identifiers[0]
    registry: tuple[list[str], int] | None = None
    best_fields: list[tuple[str, str]] = []
    field_source = 0
    for source_number, document in enumerate(documents, start=1):
        content = document.page_content
        if target not in content:
            continue
        for line in content.splitlines():
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and cells[0] == target:
                registry = (cells, source_number)
                break
        for match in re.finditer(r"\b[A-Z][A-Za-z0-9_]*(?:Event|Payload)\s*\(", content):
            body = _balanced_call_body(content, match.end() - 1)
            fields = [
                (name, value.strip())
                for name, value in re.findall(
                    r"(?m)^\s*([A-Za-z_]\w*)\s*=\s*([^,\n]+),?\s*$", body
                )
            ]
            if len(fields) > len(best_fields):
                best_fields = fields
                field_source = source_number
    if len(best_fields) < 3:
        return None

    citations: list[int] = []
    if registry is not None:
        cells, source_number = registry
        citations.append(source_number)
        if language == "es":
            direct = (
                f"El contrato `{cells[0]}` usa el nombre de wire `{cells[1]}`, "
                f"id numérico {cells[2]} y versión `{cells[3]}` [SOURCE {source_number}]."
            )
        else:
            direct = (
                f"The `{cells[0]}` contract uses wire name `{cells[1]}`, numeric event id "
                f"{cells[2]}, and version `{cells[3]}` [SOURCE {source_number}]."
            )
    else:
        direct = (
            f"The indexed implementation declares payload assignments for `{target}` "
            f"[SOURCE {field_source}]."
        )
    citations.append(field_source)
    header = "| Field | Type | Required | Description | Source |"
    separator = "|---|---|---|---|---|"
    rows = [
        f"| `{name}` | — | — | `{name} = {value}` | [SOURCE {field_source}] |"
        for name, value in best_fields
    ]
    missing = (
        ["Field types and required/optional constraints are not present in the selected evidence."]
        if language != "es"
        else ["Los tipos y las restricciones obligatorio/opcional no aparecen en la evidencia seleccionada."]
    )
    return GroundedAnswer(
        answer="\n".join((direct, "", "### Payload fields", header, separator, *rows)),
        citations=list(dict.fromkeys(citations)),
        missing_information=missing,
    )


def _balanced_call_body(value: str, opening_index: int) -> str:
    depth = 0
    for index in range(opening_index, len(value)):
        if value[index] == "(":
            depth += 1
        elif value[index] == ")":
            depth -= 1
            if depth == 0:
                return value[opening_index + 1 : index]
    return ""


def _deterministic_delivery_answer(
    question: str, documents: list[Document], language: str
) -> GroundedAnswer | None:
    """Answer an unambiguous single-issue Jira lookup without an LLM call."""

    if len(documents) != 1 or _document_source_type(documents[0]) != "ISSUE":
        return None
    normalized = " ".join(_normalized_words(question))
    status_question = bool(re.search(
        r"\b(?:status|project status|delivery status|release status|estado)\b",
        normalized,
    ))
    details_question = bool(re.search(
        r"\b(?:detail|details|information|info|ticket|issue|jira)\b",
        normalized,
    ))
    if not status_question and not details_question:
        return None
    document = documents[0]
    title = str(document.metadata.get("title") or "").strip()
    status = str(document.metadata.get("status") or "").strip()
    priority = str(document.metadata.get("priority") or "").strip()
    if not title or not status:
        return None

    requested_identifiers = _jira_identifiers(question)
    indexed_identifiers = _jira_identifiers(
        " ".join(
            str(value or "")
            for value in (
                document.metadata.get("issue_key"),
                document.metadata.get("reference"),
                title,
                document.page_content,
            )
        )
    )
    matched_identifier = next(
        (
            indexed
            for requested in requested_identifiers
            for indexed in indexed_identifiers
            if _edit_distance_at_most_one(requested, indexed)
        ),
        None,
    )
    if requested_identifiers and matched_identifier is None:
        return None

    if status_question and not details_question:
        if language == "es":
            detail = f"El estado de '{title}' es '{status}'"
            if priority:
                detail += f" con prioridad {priority}"
        else:
            detail = f"The status of '{title}' is '{status}'"
            if priority:
                detail += f" with {priority.lower()} priority"
        return GroundedAnswer(
            answer=f"{detail} [SOURCE 1].",
            citations=[1],
            missing_information=[],
        )

    issue_key = str(
        document.metadata.get("issue_key") or document.metadata.get("reference") or ""
    ).strip()
    issue_type = str(document.metadata.get("issue_type") or "").strip()
    assignee = str(document.metadata.get("assignee") or "").strip()
    due_date = str(document.metadata.get("due_date") or "").strip()
    corrected = bool(
        requested_identifiers
        and matched_identifier
        and requested_identifiers[0] != matched_identifier
    )
    if language == "es":
        prefix = ""
        if corrected:
            prefix = (
                f"Usando el identificador indexado único '{matched_identifier}' para "
                f"la solicitud '{requested_identifiers[0]}', "
            )
        detail = f"El issue de Jira '{issue_key}' — '{title}'"
        if issue_type:
            detail += f" es de tipo {issue_type}"
        detail += f" y tiene estado '{status}'"
        if priority:
            detail += f" con prioridad {priority}"
        if assignee:
            detail += f"; responsable: {assignee}"
        if due_date:
            detail += f"; fecha límite: {due_date}"
    else:
        prefix = ""
        if corrected:
            prefix = (
                f"Using the uniquely indexed identifier '{matched_identifier}' for "
                f"the request '{requested_identifiers[0]}', "
            )
        detail = f"Jira issue '{issue_key}' — '{title}'"
        if issue_type:
            detail += f" is a {issue_type}"
        detail += f" with status '{status}'"
        if priority:
            detail += f" and {priority.lower()} priority"
        if assignee:
            detail += f"; assignee: {assignee}"
        if due_date:
            detail += f"; due date: {due_date}"
    return GroundedAnswer(
        answer=f"{prefix}{detail} [SOURCE 1].",
        citations=[1],
        missing_information=[],
    )


def _jira_identifiers(value: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            match.upper()
            for match in re.findall(r"\b[A-Z][A-Z0-9]*-\d+\b", value, re.IGNORECASE)
        )
    )


def _edit_distance_at_most_one(left: str, right: str) -> bool:
    """Return true for an exact match or one insertion, deletion, or substitution."""

    left, right = left.upper(), right.upper()
    if left == right:
        return True
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) > len(right):
        left, right = right, left
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) == 1
    mismatch = 0
    for index, character in enumerate(left):
        if character != right[index + mismatch]:
            mismatch += 1
            if mismatch > 1 or character != right[index + mismatch]:
                return False
    return True


def _deterministic_code_location_answer(
    question: str,
    documents: list[Document],
    language: str,
    code_extensions: tuple[str, ...] = (),
) -> GroundedAnswer | None:
    """Extract strongly matching filenames for natural code-location questions."""

    query_terms = _code_location_terms(question)
    if not query_terms:
        return None
    matches: list[tuple[int, int, str, int]] = []
    seen: set[str] = set()
    for source_number, document in enumerate(documents, start=1):
        for label in _code_location_values(document, code_extensions):
            identity = label.casefold()
            if identity in seen:
                continue
            score = _code_location_label_score(query_terms, label)
            if score:
                seen.add(identity)
                matches.append((score, -source_number, label, source_number))
    if not matches:
        return None
    best_score = max(item[0] for item in matches)
    selected = sorted(
        (item for item in matches if item[0] == best_score),
        key=lambda item: (item[1], item[2].casefold()),
        reverse=True,
    )[:3]
    citations = list(dict.fromkeys(item[3] for item in selected))
    if len(selected) == 1:
        prefix = "El archivo coincidente es" if language == "es" else "The matching file is"
        answer = f"{prefix} `{selected[0][2]}` [SOURCE {selected[0][3]}]."
    else:
        prefix = "Los archivos coincidentes son:" if language == "es" else "The matching files are:"
        answer = prefix + "\n" + "\n".join(
            f"- `{label}` [SOURCE {source_number}]."
            for _score, _rank, label, source_number in selected
        )
    return GroundedAnswer(
        answer=answer,
        citations=citations,
        missing_information=[],
    )


_CODE_LOCATION_IGNORED = {
    "a", "an", "and", "are", "class", "classes", "code", "does", "file",
    "files", "for", "function", "functions", "has", "have", "in", "is", "it",
    "method", "methods", "of", "repository", "source", "the", "what", "where",
    "which", "with", "you",
}


def _code_location_terms(question: str) -> set[str]:
    normalized = " ".join(_normalized_words(question))
    if not re.search(
        # Users commonly ask this as “which code has …”, “what code contains
        # …”, or “where is … implemented”, not only as “which file …”. Treat
        # all of these as a bounded location lookup so the answer can be
        # selected from indexed paths/symbols instead of guessed by the LLM.
        r"\b(?:which|what)\s+(?:(?:source|github|repository)\s+)?(?:files?|code|class(?:es)?|methods?|functions?)\b|"
        r"\bwhere\b|"
        r"\b(?:files?|code|classes?|methods?|functions?)\s+(?:has|have|contains?|defines?|implements?|includes?)\b",
        normalized,
    ):
        return set()
    return {
        _singular_key(word)
        for word in _normalized_words(question)
        if word not in _CODE_LOCATION_IGNORED
    }


def _code_file_pattern(code_extensions: tuple[str, ...]) -> re.Pattern[str] | None:
    suffixes = [re.escape(value.lstrip(".")) for value in code_extensions if value]
    if not suffixes:
        return None
    return re.compile(
        r"(?<![\w./-])(?:[A-Za-z0-9_.-]+/)*[A-Za-z][A-Za-z0-9_.-]*\."
        rf"(?:{'|'.join(suffixes)})\b",
        flags=re.IGNORECASE,
    )


def _code_location_values(
    document: Document, code_extensions: tuple[str, ...] = ()
) -> list[str]:
    pattern = _code_file_pattern(code_extensions)
    values = (
        [match.group(0) for match in pattern.finditer(document.page_content)]
        if pattern is not None
        else []
    )
    metadata_path = str(document.metadata.get("path") or "").strip()
    if metadata_path and (pattern is None or pattern.fullmatch(metadata_path)):
        values.insert(0, metadata_path)
    return [
        value if value == metadata_path else value.rsplit("/", 1)[-1]
        for value in values
    ]


def _code_location_label_score(query_terms: set[str], label: str) -> int:
    candidate_terms = set(_identifier_components(label.rsplit(".", 1)[0]))
    return sum(
        any(
            query == candidate
            or (
                min(len(query), len(candidate)) >= 4
                and (query.startswith(candidate) or candidate.startswith(query))
            )
            for candidate in candidate_terms
        )
        for query in query_terms
    )


def _code_location_document_score(
    question: str, document: Document, code_extensions: tuple[str, ...] = ()
) -> int:
    query_terms = _code_location_terms(question)
    return max(
        (
            _code_location_label_score(query_terms, label)
            for label in _code_location_values(document, code_extensions)
        ),
        default=0,
    )


def _deterministic_feature_inventory_answer(
    documents: list[Document], language: str, entity: str
) -> GroundedAnswer | None:
    if not documents:
        return None
    bullets: list[str] = []
    citations: list[int] = []
    for source_number, document in enumerate(documents, start=1):
        title = str(document.metadata.get("title") or "").strip()
        name = _feature_name_from_title(title, entity)
        if not name:
            continue
        bullets.append(f"- {name} [SOURCE {source_number}].")
        citations.append(source_number)
    if not bullets:
        return None
    return GroundedAnswer(
        answer="\n".join(bullets),
        citations=citations,
        missing_information=[],
    )


def _feature_name_from_title(title: str, entity: str) -> str:
    value = re.sub(
        rf"^{re.escape(entity)}[-_\s]+",
        "",
        title,
        flags=re.IGNORECASE,
    )
    value = re.sub(
        r"[-_\s]+Documentation$",
        "",
        value,
        flags=re.IGNORECASE,
    )
    value = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", value)
    return re.sub(r"[-_\s]+", " ", value).strip()


def _feature_inventory_answer_verified(
    answer: GroundedAnswer, documents: list[Document], entity: str
) -> bool:
    if answer.citations != list(range(1, len(documents) + 1)):
        return False
    expected = [
        f"- {_feature_name_from_title(str(document.metadata.get('title') or ''), entity)} "
        f"[SOURCE {source_number}]."
        for source_number, document in enumerate(documents, start=1)
    ]
    actual = [line.strip() for line in answer.answer.splitlines() if line.strip()]
    return actual == expected


def _code_inventory_documents(
    documents: list[Document], maximum: int, question: str = ""
) -> list[Document]:
    question_words = set(_normalized_words(question))
    requires_symbol = bool(
        question_words
        & {
            "class",
            "classes",
            "function",
            "functions",
            "method",
            "methods",
            "clase",
            "clases",
            "funcion",
            "funciones",
            "metodo",
            "metodos",
        }
    )
    generic_words = {
        "all",
        "and",
        "about",
        "code",
        "complete",
        "every",
        "file",
        "files",
        "full",
        "in",
        "indexed",
        "list",
        "of",
        "for",
        "from",
        "project",
        "source",
        "the",
        "with",
        "class",
        "classes",
        "function",
        "functions",
        "method",
        "methods",
        "module",
        "modules",
        "application",
        "app",
        "t2",
        "aaos",
        "todos",
        "todas",
        "de",
        "del",
        "el",
        "en",
        "la",
        "las",
        "los",
        "y",
        "codigo",
        "archivos",
        "clase",
        "clases",
        "funcion",
        "funciones",
        "metodo",
        "metodos",
        "modulo",
        "modulos",
    }
    anchors = question_words - generic_words
    unique: dict[tuple[str, str, str, str], Document] = {}
    for document in documents:
        if _document_source_type(document) != "CODE":
            continue
        symbol = str(document.metadata.get("symbol") or "")
        if requires_symbol and not symbol:
            continue
        searchable_metadata = " ".join(
            _normalized_words(
                " ".join(
                    (
                        str(document.metadata.get("path") or ""),
                        str(document.metadata.get("title") or ""),
                        symbol,
                    )
                )
            )
        )
        if anchors and not all(anchor in searchable_metadata for anchor in anchors):
            continue
        identity = (
            str(document.metadata.get("repository") or ""),
            str(document.metadata.get("branch") or ""),
            str(document.metadata.get("path") or document.metadata.get("reference") or ""),
            symbol,
        )
        if identity[2]:
            unique.setdefault(identity, document)
    return list(unique.values())[:maximum]


def _code_inventory_label(document: Document) -> str:
    path = str(document.metadata.get("path") or document.metadata.get("reference") or "").strip()
    symbol = str(document.metadata.get("symbol") or "").strip()
    return f"{symbol} — {path}" if symbol else path


def _deterministic_code_inventory_answer(
    documents: list[Document], language: str
) -> GroundedAnswer | None:
    if not documents:
        return None
    bullets = [
        f"- {_code_inventory_label(document)} [SOURCE {source_number}]."
        for source_number, document in enumerate(documents, start=1)
    ]
    return GroundedAnswer(
        answer="\n".join(bullets),
        citations=list(range(1, len(documents) + 1)),
        missing_information=[],
    )


def _code_inventory_answer_verified(
    answer: GroundedAnswer, documents: list[Document]
) -> bool:
    if answer.citations != list(range(1, len(documents) + 1)):
        return False
    return all(
        _code_inventory_label(document) in answer.answer
        and f"[SOURCE {source_number}]" in answer.answer
        for source_number, document in enumerate(documents, start=1)
    )
