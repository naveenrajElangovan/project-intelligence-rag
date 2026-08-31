from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import TypeVar


T = TypeVar("T")
_TRANSIENT_STATUS_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_NON_RETRYABLE_QUOTA_MARKERS = (
    "EMBEDDING TOKEN LIMIT",
    "CURRENT MONTH",
    "QUOTA",
)


def is_transient_error(error: Exception) -> bool:
    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    text = f"{type(error).__name__} {error}".upper()
    # A monthly provider quota cannot be fixed by retrying. Avoid wasting
    # latency and producing duplicate provider calls for a deterministic 429.
    if status == 429 and any(marker in text for marker in _NON_RETRYABLE_QUOTA_MARKERS):
        return False
    if status in _TRANSIENT_STATUS_CODES:
        return True
    name = type(error).__name__.lower()
    text = str(error).lower()
    return any(
        marker in name or marker in text
        for marker in (
            "timeout",
            "temporar",
            "connection",
            "rate limit",
            "resource_exhausted",
            "service unavailable",
        )
    )


async def with_transient_retry(
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int,
    timeout_seconds: float,
    base_delay_seconds: float = 0.2,
) -> tuple[T, int]:
    """Run a dependency operation with a deadline and transient-only retries."""

    if attempts < 1:
        raise ValueError("Retry attempts must be at least one.")
    retries = 0
    for attempt in range(attempts):
        try:
            return await asyncio.wait_for(operation(), timeout=timeout_seconds), retries
        except Exception as error:
            if attempt + 1 >= attempts or not is_transient_error(error):
                raise
            retries += 1
            delay = min(2.0, base_delay_seconds * (2**attempt))
            await asyncio.sleep(delay + random.uniform(0, delay / 4))
    raise RuntimeError("Unreachable retry state.")
