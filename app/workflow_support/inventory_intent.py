"""Generic inventory-intent detection without domain or provider allowlists."""

from __future__ import annotations

import re

from app.workflow_support.identifiers import member_identifiers


_EXPLICIT_INVENTORY = re.compile(
    r"\b(?:list|enumerate|show|give|tell)\b.{0,40}\b(?:all|every|available|supported|existing|configured|defined)\b",
    re.IGNORECASE,
)
_ALL_ITEMS = re.compile(
    r"\b(?:all|every)\b.{0,60}\b[a-z][a-z0-9_-]*s\b",
    re.IGNORECASE,
)
_PLURAL_QUESTION = re.compile(
    r"\b(?:what|which)\s+are\b.{0,60}\b[a-z][a-z0-9_-]*s\b",
    re.IGNORECASE,
)
_PLURAL_SUBJECT_QUESTION = re.compile(
    r"\b(?:what|which)\s+[a-z][a-z0-9_-]*s\s+(?:are|exist|remain|apply)\b",
    re.IGNORECASE,
)
_PLURAL_AUXILIARY_QUESTION = re.compile(
    r"\b(?:what|which)\s+(?:[a-z][a-z0-9_-]*\s+){0,2}[a-z][a-z0-9_-]*s\s+"
    r"(?:does|do|did|can|could|will|would|should)\b",
    re.IGNORECASE,
)
_PLURAL_EXISTENCE = re.compile(
    r"\b[a-z][a-z0-9_-]*s\s+"
    r"(?:exist|are\s+there|are\s+available|are\s+supported|are\s+defined)\b",
    re.IGNORECASE,
)
_INVENTORY_NOUN = re.compile(
    r"\b(?:inventory|catalog|registry|matrix|available options|supported values)\b",
    re.IGNORECASE,
)


def is_inventory_question(question: str) -> bool:
    """Return true when the user requests a collection rather than one fact."""

    normalized = " ".join(question.split())
    if member_identifiers(normalized):
        return False
    return any(
        pattern.search(normalized)
        for pattern in (
            _EXPLICIT_INVENTORY,
            _ALL_ITEMS,
            _PLURAL_QUESTION,
            _PLURAL_SUBJECT_QUESTION,
            _PLURAL_AUXILIARY_QUESTION,
            _PLURAL_EXISTENCE,
            _INVENTORY_NOUN,
        )
    )
