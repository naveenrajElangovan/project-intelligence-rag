"""Safe classification of provider failures raised during retrieval."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievalFailure:
    code: str
    status_code: int | None
    retryable: bool


_QUOTA_MARKERS = (
    "EMBEDDING TOKEN LIMIT",
    "CURRENT MONTH",
    "QUOTA",
    "RESOURCE_EXHAUSTED",
)


def classify_retrieval_failure(error: BaseException) -> RetrievalFailure:
    """Return a bounded, provider-neutral failure category.

    Error bodies are intentionally not returned. Provider responses can contain
    request details, so telemetry records only the stable category and status.
    """

    status = getattr(error, "status", None) or getattr(error, "status_code", None)
    status_code = int(status) if isinstance(status, int) else None
    text = f"{type(error).__name__} {error}".upper()
    if status_code == 429 and any(marker in text for marker in _QUOTA_MARKERS):
        return RetrievalFailure("EMBEDDING_QUOTA_EXHAUSTED", status_code, False)
    if status_code == 429 or "RATE LIMIT" in text:
        return RetrievalFailure("RATE_LIMITED", status_code or 429, True)
    if status_code in {401, 403}:
        return RetrievalFailure("PROVIDER_AUTH_FAILED", status_code, False)
    if status_code == 404:
        return RetrievalFailure("INDEX_NOT_FOUND", status_code, False)
    if status_code == 400:
        return RetrievalFailure("INVALID_PROVIDER_REQUEST", status_code, False)
    if status_code is not None and 500 <= status_code <= 599:
        return RetrievalFailure("PROVIDER_UNAVAILABLE", status_code, True)
    if "TIMEOUT" in text or "DEADLINE_EXCEEDED" in text:
        return RetrievalFailure("PROVIDER_TIMEOUT", status_code, True)
    if "CONNECTION" in text or "TEMPORAR" in text:
        return RetrievalFailure("PROVIDER_CONNECTION_FAILED", status_code, True)
    return RetrievalFailure("UNKNOWN_RETRIEVAL_FAILURE", status_code, False)
