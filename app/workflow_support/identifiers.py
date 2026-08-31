"""Shared recognition of corpus member identifiers."""

from __future__ import annotations

import re


def member_identifiers(text: str) -> tuple[str, ...]:
    """Return ordered, unique multi-part screaming-snake identifiers."""

    return tuple(
        dict.fromkeys(
            identifier
            for identifier in re.findall(r"\b[A-Z][A-Z0-9_]{2,}\b", text)
            if "_" in identifier
        )
    )
