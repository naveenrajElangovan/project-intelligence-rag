"""Authenticated client for the macOS model accelerator used by Docker RAG."""

from __future__ import annotations

import json
import socket
import threading
import time
from functools import lru_cache
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# These mirror the request contract declared in app/inference_api.py. The worker
# rejects an oversized request with 422, which reaches a caller as an opaque
# "request failed" and loses the whole answer. Callers batch and clamp against
# these constants instead: the limits belong to the wire format, so they live
# next to the client that has to satisfy them.
MAX_EMBED_TEXTS = 32
MAX_RERANK_PAIRS = 64
MAX_QUERY_CHARACTERS = 4_000
MAX_EVIDENCE_CHARACTERS = 16_000


@lru_cache(maxsize=8)
def _accelerator_semaphore(capacity: int) -> threading.BoundedSemaphore:
    """Share one process-wide bound across embedding and scoring callers."""

    return threading.BoundedSemaphore(capacity)


def _is_replayable(error: Exception) -> bool:
    """True only when the worker cannot have started the work.

    A timeout is deliberately excluded. The worker is probably still holding the
    GPU for the request that lapsed, and sending a second copy is precisely the
    amplification this service was rebuilt to remove.
    """

    if isinstance(error, (TimeoutError, socket.timeout)):
        return False
    if isinstance(error, HTTPError):
        return error.code in {502, 503, 504}
    return isinstance(error, URLError) and not isinstance(
        getattr(error, "reason", None), (TimeoutError, socket.timeout)
    )


def accelerator_request(
    base_url: str,
    path: str,
    payload: dict[str, object] | None,
    *,
    api_key: str,
    timeout_seconds: float,
    attempts: int = 1,
    max_concurrency: int = 1,
) -> dict[str, Any]:
    """Call the loopback accelerator without exposing its credential in payloads."""

    body = None if payload is None else json.dumps(payload).encode("utf-8")
    last_error: Exception | None = None
    with _accelerator_semaphore(max_concurrency):
        for attempt in range(max(1, attempts)):
            request = Request(
                f"{base_url.rstrip('/')}{path}",
                data=body,
                method="GET" if body is None else "P" + "OST",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {api_key}",
                    **({"Content-Type": "application/json"} if body is not None else {}),
                },
            )
            try:
                with urlopen(request, timeout=timeout_seconds) as response:
                    value = json.loads(response.read())
            except (HTTPError, URLError, TimeoutError) as error:
                last_error = error
                if attempt + 1 >= max(1, attempts) or not _is_replayable(error):
                    raise RuntimeError(
                        f"Local accelerator request failed: {type(error).__name__}"
                    ) from error
                time.sleep(0.2 * (2**attempt))
                continue
            if not isinstance(value, dict):
                raise RuntimeError("Local accelerator returned an invalid response.")
            return value
    raise RuntimeError(
        f"Local accelerator request failed: {type(last_error).__name__}"
    ) from last_error


def accelerator_embed(
    base_url: str,
    texts: list[str],
    *,
    api_key: str,
    timeout_seconds: float,
    dimensions: int,
    attempts: int = 1,
    max_concurrency: int = 1,
) -> list[list[float]]:
    """Embed any number of texts, in requests the worker will accept."""

    vectors: list[list[float]] = []
    for start in range(0, len(texts), MAX_EMBED_TEXTS):
        batch = texts[start : start + MAX_EMBED_TEXTS]
        response = accelerator_request(
            base_url,
            "/embed",
            {"texts": batch},
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            max_concurrency=max_concurrency,
        )
        returned = response.get("vectors")
        if not isinstance(returned, list) or len(returned) != len(batch):
            raise RuntimeError("Local accelerator returned invalid embedding vectors.")
        for vector in returned:
            if not isinstance(vector, list) or len(vector) != dimensions:
                raise RuntimeError(
                    "Local accelerator returned the wrong embedding dimensions."
                )
            vectors.append([float(value) for value in vector])
    return vectors


def accelerator_scores(
    base_url: str,
    pairs: list[tuple[str, str]],
    *,
    api_key: str,
    timeout_seconds: float,
    max_length: int,
    attempts: int = 1,
    max_concurrency: int = 1,
) -> list[float]:
    """Score any number of pairs, in requests the worker will accept.

    Truncation here is a last line of defence, not the intended path. Callers
    size evidence deliberately; this only prevents a pair that grew past the
    wire limit -- table linearisation expands text after it was sized -- from
    failing the entire answer.
    """

    scores: list[float] = []
    clamped = [
        (query[:MAX_QUERY_CHARACTERS], evidence[:MAX_EVIDENCE_CHARACTERS])
        for query, evidence in pairs
    ]
    for start in range(0, len(clamped), MAX_RERANK_PAIRS):
        batch = clamped[start : start + MAX_RERANK_PAIRS]
        response = accelerator_request(
            base_url,
            "/rerank",
            {
                "pairs": [
                    {"query": query, "evidence": evidence} for query, evidence in batch
                ],
                "max_length": max_length,
            },
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            attempts=attempts,
            max_concurrency=max_concurrency,
        )
        returned = response.get("scores")
        if not isinstance(returned, list) or len(returned) != len(batch):
            raise RuntimeError("Local accelerator returned invalid scores.")
        scores.extend(float(value) for value in returned)
    return scores
