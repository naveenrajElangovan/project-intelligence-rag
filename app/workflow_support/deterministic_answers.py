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


_EXTRACTIVE_QUERY_NOISE = {
    "about", "all", "anything", "are", "can", "could", "details", "does",
    "explain", "for", "from", "give", "have", "here", "how", "in", "is",
    "me", "of", "project", "tell", "the", "this", "what", "where", "which",
    "with", "you", "algo", "aqui", "cómo", "cual", "cuáles", "dame", "de",
    "del", "donde", "el", "en", "esta", "este", "explica", "hay", "la",
    "las", "los", "me", "para", "proyecto", "que", "qué", "sobre", "tiene",
}


def _has_strong_evidence_anchor(question: str, documents: list[Document]) -> bool:
    """Return whether authorized evidence contains the question's concrete subject.

    This is a provider- and domain-neutral fail-closed guard for the narrow case
    where semantic context evaluation reported zero relevance. It does not rank
    documents or decide whether a claim is true; it prevents a grounded answer
    about a neighboring subject from being released as an answer to the question.
    """

    query_words = tuple(
        dict.fromkeys(
            word
            for word in _normalized_words(question)
            if len(word) >= 3
            and word not in _EXTRACTIVE_QUERY_NOISE
            and not re.fullmatch(r"t?\d+(?:\.\d+)*", word)
        )
    )
    if not query_words:
        return False
    required_overlap = len(query_words) if len(query_words) <= 2 else 2
    for document in documents:
        evidence_words = set(_normalized_words(document.page_content))
        if sum(word in evidence_words for word in query_words) >= required_overlap:
            return True
        metadata_words = set(
            _normalized_words(
                " ".join(
                    str(document.metadata.get(field) or "")
                    for field in ("title", "reference", "issue_key", "locator")
                )
            )
        )
        if sum(word in metadata_words for word in query_words) >= required_overlap:
            return True
    return False


def _deterministic_extractive_answer(
    question: str, documents: list[Document], language: str
) -> GroundedAnswer | None:
    """Recover an answer by quoting strongly matching authorized evidence.

    This is the final recovery path when a generated paraphrase cannot pass the
    grounding model. It is deliberately domain and provider neutral. Candidate
    windows must share every meaningful query term when the question has at most
    two, or at least two terms for a longer question. The output copies complete
    source sentences, so it cannot introduce a fact that is absent from the
    indexed evidence.
    """

    query_words = tuple(
        dict.fromkeys(
            word
            for word in _normalized_words(question)
            if len(word) >= 3
            and word not in _EXTRACTIVE_QUERY_NOISE
            and not re.fullmatch(r"t?\d+(?:\.\d+)*", word)
        )
    )
    if not query_words:
        return None
    required_overlap = len(query_words) if len(query_words) <= 2 else 2
    ranked: list[tuple[tuple[float, ...], int, tuple[str, ...]]] = []
    for source_number, document in enumerate(documents, start=1):
        raw_segments = re.split(r"(?<=[.!?])\s+|\n+", document.page_content)
        segments = [
            " ".join(segment.strip().strip("#>*- ").split())
            for segment in raw_segments
            if segment.strip()
        ]
        for start in range(len(segments)):
            for width in range(1, min(3, len(segments) - start) + 1):
                window = tuple(
                    segment for segment in segments[start : start + width]
                    if 4 <= len(re.findall(r"\w+", segment)) <= 100
                )
                if not window:
                    continue
                folded = " ".join(window).casefold()
                overlap = sum(word in set(_normalized_words(folded)) for word in query_words)
                if overlap < required_overlap:
                    continue
                phrase_bonus = int(" ".join(query_words) in folded)
                anchor_words = set(_normalized_words(window[0]))
                anchor_overlap = sum(word in anchor_words for word in query_words)
                metadata = document.metadata
                authority = {"PAGE": 3, "ISSUE": 2, "CODE": 1}.get(
                    str(metadata.get("source_type") or "").upper(), 0
                )
                retrieval = max(
                    float(metadata.get("rerank_score") or 0.0),
                    float(metadata.get("lexical_score") or 0.0),
                    float(metadata.get("score") or 0.0),
                )
                word_count = sum(len(re.findall(r"\w+", value)) for value in window)
                prose_window = int(not any("|" in value for value in window))
                ranked.append(
                    (
                        (
                            float(overlap),
                            float(phrase_bonus),
                            float(anchor_overlap),
                            float(authority),
                            float(prose_window),
                            float(len(window)),
                            retrieval,
                            -float(word_count),
                        ),
                        source_number,
                        window,
                    )
                )
    if not ranked:
        return None
    _score, source_number, window = max(ranked, key=lambda item: item[0])
    substantive = tuple(
        sentence
        for sentence in window
        if not re.search(
            r"(?:section identity|retrieval terms|document id|"
            r"identidad de secci[oó]n|t[eé]rminos de recuperaci[oó]n)\s*:",
            sentence,
            re.IGNORECASE,
        )
    )
    if substantive:
        window = substantive
    cited_sentences = [
        f"{sentence.rstrip('.')} [SOURCE {source_number}]." for sentence in window
    ]
    heading = " ".join(question.split()).strip("# ")
    return GroundedAnswer(
        answer=f"### {heading}\n" + "\n".join(cited_sentences),
        citations=[source_number],
        missing_information=[],
    )


def _deterministic_canonical_route_answer(
    question: str, documents: list[Document], language: str
) -> GroundedAnswer | None:
    """Quote the most topical instruction from an exact canonical route.

    This is intentionally limited to documents independently marked as route
    matches during authorized retrieval. It copies existing prose rather than
    synthesizing a new procedure; normal citation and grounding checks still
    run afterward.
    """

    words = {
        word
        for word in _normalized_words(question)
        if len(word) >= 5
        and word not in {"which", "where", "about", "cómo", "donde", "sobre"}
    }
    stems = {
        word[:-4] if word.endswith("idad") else word[:-3] if word.endswith("ity") else word
        for word in words
    }
    if not stems:
        return None
    matches: list[tuple[int, int, str]] = []
    for source_number, document in enumerate(documents, start=1):
        if not document.metadata.get("canonical_route_match"):
            continue
        for segment in re.split(r"(?<=[.!?])\s+|\n+", document.page_content):
            cleaned = " ".join(segment.split()).strip(" -*")
            if len(re.findall(r"\w+", cleaned)) < 4:
                continue
            folded = cleaned.casefold()
            score = sum(stem in folded for stem in stems)
            if score:
                matches.append((score, -source_number, cleaned))
    if not matches:
        return None
    _score, negative_source, text = max(matches)
    source_number = -negative_source
    heading = " ".join(question.split()).strip("# ")
    return GroundedAnswer(
        answer=f"### {heading}\n{text.rstrip('.')} [SOURCE {source_number}].",
        citations=[source_number],
        missing_information=[],
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
    """Render an exact event registry row and its declared payload model."""

    identifiers = re.findall(r"\b[A-Z][A-Z0-9_]{4,}\b", question)
    if not identifiers:
        return None
    target = identifiers[0]
    registry: tuple[list[str], int] | None = None
    aliases = {target}
    for source_number, document in enumerate(documents, start=1):
        for line in document.page_content.splitlines():
            cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
            if len(cells) < 4 or not _registry_identifier_matches(target, cells[:2]):
                continue
            registry = (cells, source_number)
            aliases.update(cells[:2])
            break

    declared_fields = _declared_entity_fields(documents, aliases)
    best_fields: list[tuple[str, str]] = []
    field_source = 0
    for source_number, document in enumerate(documents, start=1):
        content = document.page_content
        if not any(alias in content for alias in aliases):
            continue
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
    if registry is None and not declared_fields and len(best_fields) < 3:
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
    elif declared_fields:
        direct = ""
    else:
        direct = (
            f"La implementación indexada declara asignaciones de payload para `{target}` "
            f"[SOURCE {field_source}]."
            if language == "es"
            else f"The indexed implementation declares payload assignments for `{target}` "
            f"[SOURCE {field_source}]."
        )
    if declared_fields:
        citations.extend(source for *_values, source in declared_fields)
        header = (
            "| Campo serializado | Propiedad de código | Tipo | Fuente |"
            if language == "es"
            else "| Serialized field | Code property | Type | Source |"
        )
        separator = "|---|---|---|---|"
        rows = [
            f"| `{serialized}` | `{property_name}` | `{field_type}` | [SOURCE {source}] |"
            for serialized, property_name, field_type, source in declared_fields
        ]
        missing: list[str] = []
    elif best_fields:
        citations.append(field_source)
        header = (
            "| Campo | Tipo | Obligatorio | Descripción | Fuente |"
            if language == "es"
            else "| Field | Type | Required | Description | Source |"
        )
        separator = "|---|---|---|---|---|"
        rows = [
            f"| `{name}` | — | — | `{name} = {value}` | [SOURCE {field_source}] |"
            for name, value in best_fields
        ]
        missing = [
            (
                "La evidencia seleccionada contiene asignaciones de payload, pero no los tipos "
                "de campo autoritativos."
                if language == "es"
                else "The selected evidence contains payload assignments but not the authoritative field types."
            )
        ]
    else:
        header = separator = ""
        rows = []
        missing = [
            (
                "La evidencia seleccionada no contenía una definición autoritativa de los "
                "campos del payload."
                if language == "es"
                else "No authoritative payload-field definition was present in the selected evidence."
            )
        ]
    table_title = "### Campos del payload" if language == "es" else "### Payload fields"
    table = ("", table_title, header, separator, *rows) if rows else ()
    return GroundedAnswer(
        answer="\n".join(part for part in (direct, *table) if part),
        citations=list(dict.fromkeys(citations)),
        missing_information=missing,
    )


def _registry_identifier_matches(target: str, identifiers: list[str]) -> bool:
    normalized = {value.removesuffix("_EVENT") for value in identifiers}
    return target in identifiers or target.removesuffix("_EVENT") in normalized


def _declared_entity_fields(
    documents: list[Document], aliases: set[str]
) -> list[tuple[str, str, str, int]]:
    """Select the strongest entity-scoped Kotlin payload declaration."""

    target_terms = {
        part.casefold()
        for alias in aliases
        for part in alias.split("_")
        if part.casefold() not in {"event", "payload"}
    }
    candidates: list[tuple[int, list[tuple[str, str, str, int]]]] = []
    for source_number, document in enumerate(documents, start=1):
        content = document.page_content
        searchable = f"{document.metadata.get('title', '')} {content}".casefold()
        for match in re.finditer(r"\bdata\s+class\s+([A-Za-z_]\w*)\s*\(", content):
            class_name = match.group(1)
            if any(alias.endswith("_EVENT") for alias in aliases) and not class_name.endswith(
                "Event"
            ):
                continue
            body = _balanced_call_body(content, match.end() - 1)
            fields = [
                (serialized or property_name, property_name, field_type.strip(), source_number)
                for serialized, property_name, field_type in re.findall(
                    r'(?:@SerialName\("([^"]+)"\)\s*)?'
                    r"(?:override\s+)?val\s+([A-Za-z_]\w*)\s*:\s*([^,\n=]+)",
                    body,
                )
            ]
            if not fields:
                continue
            prelude = content[max(0, match.start() - 180) : match.start()]
            class_aliases = set(re.findall(r'@SerialName\("([^"]+)"\)', prelude))
            exact_alias = bool(class_aliases.intersection(aliases))
            term_matches = sum(term in searchable for term in target_terms)
            has_registry_alias = len(aliases) > 1
            if (has_registry_alias and not exact_alias) or (
                not exact_alias and not term_matches
            ):
                continue
            candidates.append((100 if exact_alias else term_matches, fields))
    if not candidates:
        return []
    return max(candidates, key=lambda candidate: (candidate[0], len(candidate[1])))[1]


def structured_entity_field_names(
    question: str, documents: list[Document]
) -> tuple[str, ...]:
    """Return the authoritative serialized field population for one entity."""

    identifiers = re.findall(r"\b[A-Z][A-Z0-9_]{4,}\b", question)
    if not identifiers:
        return ()
    target = identifiers[0]
    aliases = {target}
    for document in documents:
        for line in document.page_content.splitlines():
            cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and _registry_identifier_matches(target, cells[:2]):
                aliases.update(cells[:2])
    return tuple(
        dict.fromkeys(
            serialized
            for serialized, _property_name, _field_type, _source in _declared_entity_fields(
                documents, aliases
            )
        )
    )


def structured_entity_aliases(
    question: str, documents: list[Document]
) -> tuple[str, ...]:
    """Resolve constant and wire aliases without embedding domain-specific names."""

    identifiers = re.findall(r"\b[A-Z][A-Z0-9_]{4,}\b", question)
    if not identifiers:
        return ()
    target = identifiers[0]
    aliases = [target]
    for document in documents:
        for line in document.page_content.splitlines():
            cells = [cell.strip().strip("`") for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 2 and _registry_identifier_matches(target, cells[:2]):
                aliases.extend(cells[:2])
    return tuple(dict.fromkeys(aliases))


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


def exact_current_issue_evidence(question: str, documents: list[Document]) -> list[Document]:
    """Select an unambiguous current Jira record from authorized candidates.

    Issue-key equality is authoritative for a current-status lookup; semantic
    similarity to a related ticket must never replace it. Multiple cloud/source
    identities remain ambiguous and are not collapsed here.
    """
    keys = _jira_identifiers(question)
    if len(keys) != 1 or not re.search(r"\b(?:status|estado)\b", question, re.I):
        return []
    if re.search(r"\b(?:previous|previously|history|historical|changed|change|why|when|before|anterior|antes|historial|histórico|históricos|cambi[oó]|cambios|por qu[eé]|cu[aá]ndo)\b", question, re.I):
        return []
    matched = [document for document in documents
        if str(document.metadata.get("issue_key") or "").upper() == keys[0]
        and document.metadata.get("jira_chunk_kind") == "CURRENT"
        and _document_source_type(document) == "ISSUE"]
    sources = {document.metadata.get("source_id") for document in matched}
    return matched if len(sources) == 1 and None not in sources else []


def _deterministic_delivery_answer(
    question: str, documents: list[Document], language: str
) -> GroundedAnswer | None:
    """Render unambiguous Jira facts while preserving each issue's citation."""

    from app.jira_query import jira_current_status_question
    requested_keys = tuple(dict.fromkeys(key.upper() for key in re.findall(
        r"\b[A-Z][A-Z0-9_]*-\d+\b", question, re.I
    )))
    if len(requested_keys) > 1 and jira_current_status_question(question):
        by_key = {}
        for index, document in enumerate(documents, 1):
            metadata = document.metadata
            key = str(metadata.get("issue_key") or "").upper()
            if (metadata.get("provider") != "JIRA"
                    or metadata.get("jira_chunk_kind") != "CURRENT"
                    or key not in requested_keys or key in by_key
                    or not metadata.get("status")):
                return None
            by_key[key] = (index, metadata)
        if set(by_key) != set(requested_keys):
            return None
        lines, citations = [], []
        for key in requested_keys:
            index, metadata = by_key[key]
            label = "Estado actual" if language == "es" else "Current status"
            lines.append(f"- {key}: {label}: {metadata['status']} [SOURCE {index}].")
            citations.append(index)
        return GroundedAnswer(answer="\n".join(lines), citations=citations, missing_information=[])
    if len(documents) != 1 or _document_source_type(documents[0]) != "ISSUE":
        return None
    normalized = " ".join(_normalized_words(question))
    if re.search(r"\b(?:previous|previously|history|historical|changed|change|why|when|before|anterior|antes|historial|cambi[oó]|por qu[eé]|cu[aá]ndo)\b", question, re.I):
        return None
    if documents[0].metadata.get("jira_chunk_kind") not in (None, "", "CURRENT"):
        return None
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
        # A Markdown heading is structural rather than a factual claim. Keeping
        # the introduction structural means every material line below carries
        # its own citation and the deterministic answer never needs an LLM
        # citation-repair pass that could alter exact paths or identifiers.
        prefix = "### Archivos coincidentes" if language == "es" else "### Matching files"
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
