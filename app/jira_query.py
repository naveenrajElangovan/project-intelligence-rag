"""Conservative, bilingual section routing for an explicitly named Jira issue."""

import re


def jira_section_query(question: str):
    keys = tuple(
        dict.fromkeys(key.upper() for key in re.findall(r"\b[A-Z][A-Z0-9_]*-\d+\b", question, re.I))
    )
    if len(keys) != 1:
        return None
    kind, event = None, None
    patterns = (
        ("COMMENT", r"\b(?:comment|comentario)\b"),
        ("WORKLOG", r"\b(?:worklog|registro de trabajo)\b"),
        ("CHANGELOG", r"\b(?:history|historical|changelog|historial|histórico|históricos)\b"),
        ("ATTACHMENT", r"\b(?:attachment|adjunto|archivo adjunto)\b"),
        ("ACCEPTANCE", r"\b(?:acceptance|aceptación)\b"),
        (
            "RELATIONSHIP",
            r"\b(?:parent|related issues|dependencies|dependency|superior|relacionadas|dependencias)\b",
        ),
        (
            "CUSTOM_FIELD",
            r"\b(?:additional field|custom field|campos adicionales|campo personalizado)\b",
        ),
        ("REMOTE_LINK", r"\b(?:external reference|remote link|referencia externa|enlace remoto)\b"),
        ("GLOSSARY", r"\b(?:define|definition|definición|glossary|glosario)\b"),
        (
            "DESCRIPTION",
            r"\b(?:behavior|described|description|requirements|comportamiento|describe|descripción|requisitos)\b",
        ),
    )
    for candidate, pattern in patterns:
        if re.search(pattern, question, re.I):
            kind = candidate
            break
    if kind in {"COMMENT", "CHANGELOG", "WORKLOG"}:
        match = re.search(
            r"\b(?:comment|comentario|event|evento|worklog|registro de trabajo)(?:\s+(?:histórico|historical))?\s+(\d+)\b",
            question,
            re.I,
        )
        event = match.group(1) if match else None
    if kind is None and re.search(r"\b(?:status|estado)\b", question, re.I):
        historical = re.search(
            r"\b(?:previous|previously|changed|change|why|when|before|anterior|antes|cambió|cambio|cambios|cuándo)\b",
            question,
            re.I,
        )
        kind = "CHANGELOG" if historical else "CURRENT"
    return keys[0], kind, event


def jira_current_status_question(question: str) -> bool:
    """Recognize current-status requests without requiring a single issue key.

    Named historical/attachment/relationship sections keep their own semantics;
    their recorded status must not be confused with a current issue-state query.
    """
    if not re.search(r"\b(?:status(?:es)?|estados?)\b", question, re.I):
        return False
    if re.search(
        r"\b(?:previous|previously|history|historical|changed|change|why|when|before|anterior(?:es)?|antes|historial|históric[oa]s?|cambi[oó]|cambios|por qu[eé]|cu[aá]ndo)\b",
        question,
        re.I,
    ):
        return False
    if re.search(
        r"\b(?:comments?|comentarios?|worklogs?|attachments?|adjuntos?|parent|parents|superior|related|relacionad[oa]s?)\b",
        question,
        re.I,
    ):
        return False
    return True


def current_jira_status_evidence(question, documents, query_intent):
    """Keep other providers unchanged; Jira current state requires CURRENT."""
    if query_intent != "DELIVERY" or not jira_current_status_question(question):
        return documents
    return [
        document
        for document in documents
        if document.metadata.get("provider") != "JIRA"
        or document.metadata.get("jira_chunk_kind") == "CURRENT"
    ]
