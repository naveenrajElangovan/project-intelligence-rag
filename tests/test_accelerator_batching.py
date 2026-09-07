"""Guardrails for the accelerator wire contract and the bounds around it."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import socket
import threading
import time
from urllib.error import HTTPError, URLError

import pytest
from langchain_core.documents import Document

from app.accelerator import (
    MAX_EMBED_TEXTS,
    MAX_EVIDENCE_CHARACTERS,
    MAX_RERANK_PAIRS,
    accelerator_embed,
    accelerator_request,
    accelerator_scores,
)
from app.config import Settings
from app.grounding import LocalCitationGroundingVerifier
from app.llm import GroundedAnswer


def _settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        environment="development",
        internal_api_key="test-accelerator-key",
        local_accelerator_url="http://host.docker.internal:8004",
        local_models_path="/models/reranker",
        local_embedding_path="/models/embedder",
        **overrides,
    )


class _Response:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exception) -> bool:
        return False


def _record_requests(monkeypatch, responder):
    """Patch the transport, returning the decoded bodies the client sent."""

    sent: list[dict] = []

    def urlopen(request, timeout=None):  # noqa: ARG001
        body = json.loads(request.data) if request.data else {}
        sent.append(body)
        return responder(body)

    monkeypatch.setattr("app.accelerator.urlopen", urlopen)
    return sent


def test_rerank_pairs_are_split_into_acceptable_requests(monkeypatch) -> None:
    """The worker caps pairs per request; a long answer must not 422."""

    sent = _record_requests(
        monkeypatch,
        lambda body: _Response({"scores": [float(len(body["pairs"]))] * len(body["pairs"])}),
    )
    pairs = [(f"claim {index}", f"evidence {index}") for index in range(150)]

    scores = accelerator_scores(
        "http://worker",
        pairs,
        api_key="key",
        timeout_seconds=5,
        max_length=1024,
    )

    assert len(scores) == 150
    assert len(sent) == 3
    assert [len(body["pairs"]) for body in sent] == [
        MAX_RERANK_PAIRS,
        MAX_RERANK_PAIRS,
        150 - 2 * MAX_RERANK_PAIRS,
    ]


def test_rerank_batches_preserve_pair_order(monkeypatch) -> None:
    _record_requests(
        monkeypatch,
        lambda body: _Response(
            {"scores": [float(pair["query"]) for pair in body["pairs"]]}
        ),
    )
    pairs = [(str(index), "evidence") for index in range(100)]

    scores = accelerator_scores(
        "http://worker", pairs, api_key="key", timeout_seconds=5, max_length=1024
    )

    assert scores == [float(index) for index in range(100)]


def test_oversized_evidence_is_clamped_to_the_wire_limit(monkeypatch) -> None:
    """Table linearisation grows evidence after it was sized."""

    sent = _record_requests(monkeypatch, lambda body: _Response({"scores": [1.0]}))

    accelerator_scores(
        "http://worker",
        [("claim", "x" * (MAX_EVIDENCE_CHARACTERS * 2))],
        api_key="key",
        timeout_seconds=5,
        max_length=1024,
    )

    assert len(sent[0]["pairs"][0]["evidence"]) == MAX_EVIDENCE_CHARACTERS


def test_embed_texts_are_split_into_acceptable_requests(monkeypatch) -> None:
    sent = _record_requests(
        monkeypatch,
        lambda body: _Response(
            {"vectors": [[0.5] * 1024 for _ in body["texts"]]}
        ),
    )

    vectors = accelerator_embed(
        "http://worker",
        [f"query {index}" for index in range(70)],
        api_key="key",
        timeout_seconds=5,
        dimensions=1024,
    )

    assert len(vectors) == 70
    assert [len(body["texts"]) for body in sent] == [
        MAX_EMBED_TEXTS,
        MAX_EMBED_TEXTS,
        70 - 2 * MAX_EMBED_TEXTS,
    ]


def test_accelerator_http_calls_share_the_configured_concurrency_bound(
    monkeypatch,
) -> None:
    active = 0
    maximum_active = 0
    lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    def urlopen(_request, timeout=None):  # noqa: ARG001
        nonlocal active, maximum_active
        with lock:
            active += 1
            maximum_active = max(maximum_active, active)
            entered.set()
        release.wait(timeout=1)
        with lock:
            active -= 1
        return _Response({"status": "ok"})

    monkeypatch.setattr("app.accelerator.urlopen", urlopen)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(
                accelerator_request,
                "http://worker",
                "/health",
                None,
                api_key="key",
                timeout_seconds=1,
                max_concurrency=1,
            )
            for _ in range(2)
        ]
        assert entered.wait(timeout=1)
        time.sleep(0.05)
        assert maximum_active == 1
        release.set()
        assert [future.result() for future in futures] == [
            {"status": "ok"},
            {"status": "ok"},
        ]

    assert maximum_active == 1


def test_a_timed_out_call_is_never_replayed(monkeypatch) -> None:
    """Resending work the worker is still doing is the original defect."""

    attempts = []

    def urlopen(request, timeout=None):  # noqa: ARG001
        attempts.append(request)
        raise socket.timeout("timed out")

    monkeypatch.setattr("app.accelerator.urlopen", urlopen)

    with pytest.raises(RuntimeError):
        accelerator_request(
            "http://worker",
            "/health",
            None,
            api_key="key",
            timeout_seconds=1,
            attempts=3,
        )

    assert len(attempts) == 1


def test_a_refused_connection_is_replayed(monkeypatch) -> None:
    attempts: list[object] = []

    def urlopen(request, timeout=None):  # noqa: ARG001
        attempts.append(request)
        if len(attempts) < 2:
            raise URLError(ConnectionRefusedError("refused"))
        return _Response({"status": "ok"})

    monkeypatch.setattr("app.accelerator.urlopen", urlopen)
    monkeypatch.setattr("app.accelerator.time.sleep", lambda _seconds: None)

    value = accelerator_request(
        "http://worker", "/health", None, api_key="key", timeout_seconds=1, attempts=2
    )

    assert value == {"status": "ok"}
    assert len(attempts) == 2


def test_a_server_error_is_replayed_but_a_rejection_is_not(monkeypatch) -> None:
    attempts: list[object] = []

    def urlopen(request, timeout=None):  # noqa: ARG001
        attempts.append(request)
        raise HTTPError("http://worker", 422, "Unprocessable", {}, None)

    monkeypatch.setattr("app.accelerator.urlopen", urlopen)
    monkeypatch.setattr("app.accelerator.time.sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError):
        accelerator_request(
            "http://worker", "/rerank", {}, api_key="key", timeout_seconds=1, attempts=3
        )

    assert len(attempts) == 1


def test_grounding_scores_each_cited_source_separately(monkeypatch) -> None:
    """Concatenating cited sources let the length cap truncate away support."""

    scored: list[tuple[str, str]] = []

    def scores(_base_url, pairs, **_kwargs):
        scored.extend(pairs)
        # Only the second cited source supports the claim. Concatenated and
        # truncated, this claim used to be dropped from the answer.
        return [-5.0 if "irrelevant" in evidence else 5.0 for _query, evidence in pairs]

    monkeypatch.setattr("app.grounding.accelerator_scores", scores)
    verifier = LocalCitationGroundingVerifier(_settings())
    documents = [
        Document(page_content="Wholly irrelevant filler text."),
        Document(page_content="The POS accepts card payments."),
    ]
    answer = GroundedAnswer(
        answer="The POS accepts card payments [SOURCE 1][SOURCE 2].",
        confidence="HIGH",
        citations=[1, 2],
    )

    verdict = asyncio.run(verifier.verify("What does the POS do?", documents, answer))

    assert verdict.supported is True
    assert len(scored) == 2
