"""Fail-open invariant for filters over already selected evidence."""

from __future__ import annotations

from typing import TypeVar


T = TypeVar("T")


def preserve_non_empty(original: list[T], filtered: list[T]) -> tuple[list[T], bool]:
    """Never allow a filter to erase an existing result set."""

    bypassed = bool(original) and not filtered
    return (original if bypassed else filtered), bypassed
