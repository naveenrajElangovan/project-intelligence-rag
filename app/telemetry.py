"""Content-free stage telemetry suitable for Loki and OpenTelemetry collection."""

from contextvars import ContextVar
import hashlib
import json
import logging
import time
import uuid
from collections.abc import Mapping
from typing import Any

from prometheus_client import Counter, Gauge, Histogram


LOGGER = logging.getLogger("project_intelligence.rag.stages")
_HANDLER_NAME = "rag-telemetry-json"
_REQUEST_ID: ContextVar[str] = ContextVar("rag_request_id", default="")
_STAGES = Counter(
    "pi_rag_stage_total",
    "Completed RAG stages.",
    ("stage", "reason_code", "model_provider", "model_profile", "language"),
)
_STAGE_DURATION = Histogram(
    "pi_rag_stage_duration_seconds",
    "RAG stage duration.",
    ("stage", "outcome"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 60),
)
_TOKENS = Counter(
    "pi_rag_tokens_total",
    "LLM and embedding token usage.",
    ("stage", "direction", "model_provider", "model_name", "model_profile"),
)
_RETRIES = Counter("pi_rag_retries_total", "Transient and semantic RAG retries.", ("stage",))
_STAGE_ITEMS = Histogram(
    "pi_rag_stage_items",
    "Items entering and leaving RAG stages.",
    ("stage", "direction"),
    buckets=(0, 1, 2, 3, 5, 8, 10, 15, 25, 50, 100),
)
_REQUESTS = Counter(
    "pi_rag_requests_total",
    "Completed RAG requests.",
    ("outcome", "confidence", "model_profile", "language"),
)
_REQUEST_DURATION = Histogram(
    "pi_rag_request_duration_seconds",
    "End-to-end RAG request duration.",
    ("outcome",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 65),
)
_RETRIEVAL_FAILURES = Counter(
    "pi_rag_retrieval_failures_total",
    "Provider failures raised during retrieval.",
    ("provider", "failure_code", "status_code", "retryable"),
)
_RETRIEVAL_FALLBACKS = Counter(
    "pi_rag_retrieval_fallback_total",
    "Authorized lexical fallbacks used after a dense retrieval provider failure.",
    ("provider", "failure_code"),
)
_RETRIEVAL_DISCARDED = Counter(
    "pi_rag_retrieval_discarded_total",
    "Searches that matched records but returned no usable evidence, by reason.",
    ("reason",),
)
_PROMPT_BUDGET_PRESSURE = Counter(
    "pi_rag_prompt_budget_pressure_total",
    "Prompts whose evidence was cut below the configured budget to fit the context "
    "window, by severity.",
    ("stage", "severity"),
)
_QUERY_ROUTES = Counter(
    "pi_rag_query_routes_total",
    "Planned RAG query routes.",
    ("query_intent", "source_route"),
)
_RETRIEVAL_CANDIDATES = Counter(
    "pi_rag_retrieval_candidates_total",
    "Authorized retrieval candidates by source type.",
    ("source_type",),
)
_EVIDENCE_SELECTED = Counter(
    "pi_rag_evidence_selected_total",
    "Final reranked evidence selected by source type.",
    ("source_type",),
)
_CODE_REQUIRED_ZERO = Counter(
    "pi_rag_code_required_zero_total",
    "Code-required requests that retrieved no CODE candidates.",
    ("query_intent",),
)
_CANONICAL_QUOTE_FALLBACKS = Counter(
    "pi_rag_canonical_quote_fallback_total",
    "Canonical quote fallbacks used after answer generation did not produce an answer.",
    ("reason",),
)
_REQUEST_ADMISSIONS = Counter(
    "pi_rag_request_admissions_total",
    "RAG requests accepted or shed at the capacity boundary.",
    ("outcome",),
)
_REQUEST_ADMISSION_WAIT = Histogram(
    "pi_rag_request_admission_wait_seconds",
    "Time spent waiting for RAG execution capacity.",
    ("outcome",),
    buckets=(0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1),
)
_INFLIGHT_REQUESTS = Gauge(
    "pi_rag_inflight_requests",
    "RAG requests currently holding an execution slot.",
)
_ADMISSION_CAPACITY = Gauge(
    "pi_rag_admission_capacity",
    "Requests this replica will admit concurrently, after clamping.",
)
_LEXICAL_CACHE_ENTRIES = Gauge(
    "pi_rag_lexical_cache_entries",
    "Bounded authorized lexical corpus cache entries.",
)
_PROVIDER_OPERATIONS = Counter(
    "pi_rag_provider_operations_total",
    "Provider operations by completion outcome.",
    ("provider", "operation", "outcome"),
)
_PROVIDER_ITEMS = Histogram(
    "pi_rag_provider_items",
    "Items returned by complete provider operations.",
    ("provider", "operation"),
    buckets=(0, 1, 5, 10, 25, 50, 100, 200, 500, 1000),
)
_STRUCTURED_CONTEXT = Counter(
    "pi_rag_structured_context_total",
    "Structured provider conversation context decisions.",
    ("outcome",),
)


def provider_operation(
    provider: str, operation: str, outcome: str, items: int, complete: bool
) -> None:
    _PROVIDER_OPERATIONS.labels(provider, operation, outcome).inc()
    if complete:
        _PROVIDER_ITEMS.labels(provider, operation).observe(max(0, items))


def structured_context_decision(outcome: str) -> None:
    _STRUCTURED_CONTEXT.labels(outcome).inc()


def configure_telemetry_logging(level: str = "INFO") -> None:
    resolved = logging.getLevelName(level.strip().upper())
    LOGGER.setLevel(resolved if isinstance(resolved, int) else logging.INFO)
    if not any(handler.get_name() == _HANDLER_NAME for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name(_HANDLER_NAME)
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.propagate = False


def new_request_id(candidate: str | None = None) -> str:
    value = (candidate or "").strip()
    if (
        value
        and len(value) <= 128
        and all(character.isalnum() or character in "-_." for character in value)
    ):
        return value
    return str(uuid.uuid4())


def set_request_id(value: str) -> object:
    return _REQUEST_ID.set(value)


def reset_request_id(token: object) -> None:
    _REQUEST_ID.reset(token)  # type: ignore[arg-type]


def request_id() -> str:
    return _REQUEST_ID.get()


def ollama_payload_fingerprint(request: object) -> dict[str, Any]:
    """Describe an Ollama request without logging prompts or evidence bodies."""

    raw = bytes(getattr(request, "content", b"") or b"")
    payload = json.loads(raw) if raw else {}
    if not isinstance(payload, dict):
        payload = {}
    options = payload.get("options")
    if not isinstance(options, dict):
        options = {}
    messages = payload.get("messages")
    prompt = payload.get("prompt")
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    messages_canonical = json.dumps(
        messages, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    sampler_keys = (
        "mirostat",
        "mirostat_eta",
        "mirostat_tau",
        "num_ctx",
        "num_gpu",
        "num_predict",
        "num_thread",
        "repeat_last_n",
        "repeat_penalty",
        "seed",
        "temperature",
        "tfs_z",
        "top_k",
        "top_p",
    )
    return {
        "event": "ollama_request_fingerprint",
        "request_id": request_id(),
        "payload_sha256": hashlib.sha256(raw).hexdigest(),
        "canonical_payload_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "messages_sha256": hashlib.sha256(messages_canonical.encode()).hexdigest(),
        "prompt_sha256": hashlib.sha256(str(prompt or "").encode()).hexdigest(),
        "payload_bytes": len(raw),
        "message_count": len(messages) if isinstance(messages, list) else 0,
        "model": str(payload.get("model") or ""),
        "method": str(getattr(request, "method", "")),
        "path": str(getattr(getattr(request, "url", None), "path", "")),
        "stream": bool(payload.get("stream")),
        "think": str(payload.get("think")),
        "format_sha256": hashlib.sha256(
            json.dumps(
                payload.get("format"),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest(),
        "options": {key: options[key] for key in sampler_keys if key in options},
    }


def log_ollama_request(request: object) -> None:
    LOGGER.info(
        json.dumps(
            ollama_payload_fingerprint(request),
            separators=(",", ":"),
            sort_keys=True,
        )
    )


async def log_ollama_request_async(request: object) -> None:
    log_ollama_request(request)


def started() -> float:
    return time.perf_counter()


def admission_capacity(capacity: int) -> None:
    """Publish the capacity actually in force.

    Model and accelerator calls are bounded separately, so this gauge reports
    only whole-request admission capacity.
    """

    _ADMISSION_CAPACITY.set(capacity)


def lexical_cache_entries(size: int) -> None:
    _LEXICAL_CACHE_ENTRIES.set(max(0, size))


def canonical_quote_fallback(reason: str) -> None:
    """Count why the canonical quote fallback was selected.

    The reason is deliberately a small machine code rather than answer content,
    so operators can distinguish timeouts, empty responses, refusals, and the
    legacy pre-generation path without placing user text in telemetry.
    """

    _CANONICAL_QUOTE_FALLBACKS.labels(reason).inc()


def request_admitted(began: float) -> None:
    _REQUEST_ADMISSIONS.labels("accepted").inc()
    _REQUEST_ADMISSION_WAIT.labels("accepted").observe(max(0.0, time.perf_counter() - began))
    _INFLIGHT_REQUESTS.inc()


def request_shed(began: float) -> None:
    _REQUEST_ADMISSIONS.labels("shed").inc()
    _REQUEST_ADMISSION_WAIT.labels("shed").observe(max(0.0, time.perf_counter() - began))


def request_released() -> None:
    _INFLIGHT_REQUESTS.dec()


def _metric_int(value: object) -> int:
    """Convert scalar telemetry fields while rejecting nested diagnostics."""
    return int(value) if isinstance(value, (bool, int, float, str)) else 0


def stage_complete(
    stage: str,
    project_id: str,
    began: float,
    *,
    input_count: int = 0,
    output_count: int = 0,
    reason_code: str = "OK",
    input_tokens: int = 0,
    output_tokens: int = 0,
    cached_tokens: int = 0,
    reasoning_tokens: int = 0,
    retry_count: int = 0,
    model_provider: str = "none",
    model_name: str = "none",
    model_profile: str = "none",
    language: str = "und",
    extra: Mapping[str, object] | None = None,
) -> None:
    duration_seconds = time.perf_counter() - began
    payload: dict[str, Any] = {
        "event": "rag_stage_complete",
        "request_id": request_id(),
        "stage": stage,
        "project_id": project_id,
        "duration_ms": round(duration_seconds * 1000, 2),
        "input_count": input_count,
        "output_count": output_count,
        "input_tokens": max(0, input_tokens),
        "output_tokens": max(0, output_tokens),
        "total_tokens": max(0, input_tokens) + max(0, output_tokens),
        "cached_tokens": max(0, cached_tokens),
        "reasoning_tokens": max(0, reasoning_tokens),
        "retry_count": max(0, retry_count),
        "reason_code": reason_code,
        "model_provider": model_provider,
        "model_name": model_name,
        "model_profile": model_profile,
        "language": language,
    }
    if extra:
        payload.update(extra)
    labels = (stage, reason_code, model_provider, model_profile, language)
    _STAGES.labels(*labels).inc()
    _STAGE_DURATION.labels(stage, reason_code).observe(duration_seconds)
    _STAGE_ITEMS.labels(stage, "input").observe(max(0, input_count))
    _STAGE_ITEMS.labels(stage, "output").observe(max(0, output_count))
    if extra and stage == "plan_queries":
        _QUERY_ROUTES.labels(
            str(extra.get("query_intent") or "DIRECT"),
            str(extra.get("source_route") or "MIXED"),
        ).inc()
    if extra and stage == "retrieve":
        for source_type, field in (
            ("CODE", "code_candidates"),
            ("PAGE", "page_candidates"),
            ("ISSUE", "issue_candidates"),
            ("ATTACHMENT", "attachment_candidates"),
        ):
            count = max(0, _metric_int(extra.get(field)))
            if count:
                _RETRIEVAL_CANDIDATES.labels(source_type).inc(count)
        if bool(extra.get("code_required")) and _metric_int(extra.get("code_candidates")) == 0:
            _CODE_REQUIRED_ZERO.labels(str(extra.get("query_intent") or "DIRECT")).inc()
    if extra and stage == "rerank":
        for source_type, field in (
            ("CODE", "code_selected"),
            ("PAGE", "page_selected"),
            ("ISSUE", "issue_selected"),
            ("ATTACHMENT", "attachment_selected"),
        ):
            count = max(0, _metric_int(extra.get(field)))
            if count:
                _EVIDENCE_SELECTED.labels(source_type).inc(count)
    if input_tokens:
        _TOKENS.labels(stage, "input", model_provider, model_name, model_profile).inc(input_tokens)
    if output_tokens:
        _TOKENS.labels(stage, "output", model_provider, model_name, model_profile).inc(
            output_tokens
        )
    if retry_count:
        _RETRIES.labels(stage).inc(retry_count)
    # Mirror safe stage telemetry into the active OpenTelemetry span. Importing
    # lazily keeps Prometheus/logging usable when tracing dependencies are absent.
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        span.add_event(
            f"rag.stage.{stage}",
            attributes={
                key: value
                for key, value in payload.items()
                if isinstance(value, (bool, int, float, str))
            },
        )
        if reason_code != "OK":
            span.set_attribute("rag.reason_code", reason_code)
    except Exception:
        pass
    LOGGER.info(json.dumps(payload, separators=(",", ":"), sort_keys=True))


def request_complete(
    *,
    began: float,
    outcome: str,
    confidence: str,
    model_profile: str,
    language: str,
    reason_code: str = "OK",
) -> None:
    duration_seconds = time.perf_counter() - began
    _REQUESTS.labels(outcome, confidence, model_profile, language).inc()
    _REQUEST_DURATION.labels(outcome).observe(duration_seconds)
    try:
        from opentelemetry import trace

        span = trace.get_current_span()
        span.set_attribute("rag.outcome", outcome)
        span.set_attribute("rag.confidence", confidence)
        span.set_attribute("rag.reason_code", reason_code)
        span.set_attribute("rag.duration_ms", round(duration_seconds * 1000, 2))
    except Exception:
        pass
    LOGGER.info(
        json.dumps(
            {
                "event": "rag_request_complete",
                "request_id": request_id(),
                "duration_ms": round(duration_seconds * 1000, 2),
                "outcome": outcome,
                "confidence": confidence,
                "model_profile": model_profile,
                "language": language,
                "reason_code": reason_code,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def retrieval_failure(
    *,
    project_id: str,
    provider: str,
    failure_code: str,
    status_code: int | None,
    retryable: bool,
    configured_attempts: int,
    model_name: str = "none",
    source_scope: str = "MIXED",
) -> None:
    """Emit safe structured telemetry for a failed provider retrieval.

    Do not include the original query, provider response body, credentials, or
    index host. The category/status fields are sufficient for alerting and
    incident diagnosis.
    """

    status_label = str(status_code) if status_code is not None else "none"
    _RETRIEVAL_FAILURES.labels(
        provider, failure_code, status_label, str(bool(retryable)).lower()
    ).inc()
    LOGGER.error(
        json.dumps(
            {
                "event": "rag_retrieval_failure",
                "request_id": request_id(),
                "project_id": project_id,
                "stage": "retrieve",
                "provider": provider,
                "failure_code": failure_code,
                "status_code": status_code,
                "retryable": retryable,
                "configured_attempts": max(1, configured_attempts),
                "model_name": model_name,
                "source_scope": source_scope,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def retrieval_discarded(
    *,
    project_id: str,
    collection_name: str,
    matched: int,
    reasons: dict[str, int],
    source_scope: str = "MIXED",
) -> None:
    """Record that every matched record was filtered out, and say why.

    Without this, a collection written under an older schema version or a
    different embedding model looks identical to a collection with nothing
    relevant in it: the provider returns matches, every one is discarded during
    filtering, and the user is told there is not enough evidence. The reason is
    knowable at the point of the drop and nowhere else.
    """

    for reason in reasons or {"unknown": matched}:
        _RETRIEVAL_DISCARDED.labels(reason.split(":", 1)[0]).inc()
    LOGGER.error(
        json.dumps(
            {
                "event": "rag_retrieval_discarded",
                "request_id": request_id(),
                "project_id": project_id,
                "stage": "retrieve",
                "collection_name": collection_name,
                "matched_records": matched,
                "reasons": reasons,
                "source_scope": source_scope,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def prompt_budget_pressure(
    *,
    stage: str,
    context_tokens: int,
    scaffold_tokens: int,
    configured_evidence_tokens: int,
    granted_evidence_tokens: int,
) -> None:
    """Record that the fixed prompt left evidence less room than configured.

    This exists because the provider does not report it. Ollama silently discards
    tokens from the start of an over-long context, which is where the system
    instructions live, so the visible symptom is a citation or grounding failure
    rather than an error. Counting it makes that cause observable.
    """

    severity = "exhausted" if granted_evidence_tokens <= 0 else "reduced"
    _PROMPT_BUDGET_PRESSURE.labels(stage, severity).inc()
    log = LOGGER.error if severity == "exhausted" else LOGGER.warning
    log(
        json.dumps(
            {
                "event": "rag_prompt_budget_pressure",
                "request_id": request_id(),
                "stage": stage,
                "severity": severity,
                "context_tokens": context_tokens,
                "scaffold_tokens": scaffold_tokens,
                "configured_evidence_tokens": configured_evidence_tokens,
                "granted_evidence_tokens": granted_evidence_tokens,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def retrieval_fallback(
    *,
    project_id: str,
    provider: str,
    failure_code: str,
    record_count: int,
    truncated: bool,
    source_scope: str = "MIXED",
) -> None:
    """Record activation of the bounded, authorized lexical fallback path."""

    _RETRIEVAL_FALLBACKS.labels(provider, failure_code).inc()
    LOGGER.warning(
        json.dumps(
            {
                "event": "rag_retrieval_fallback",
                "request_id": request_id(),
                "project_id": project_id,
                "stage": "retrieve",
                "provider": provider,
                "failure_code": failure_code,
                "fallback": "bm25",
                "record_count": max(0, record_count),
                "truncated": truncated,
                "source_scope": source_scope,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
