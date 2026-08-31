"""Content-free stage telemetry suitable for Loki and OpenTelemetry collection."""

from contextvars import ContextVar
import json
import logging
import time
import uuid
from typing import Any

from prometheus_client import Counter, Histogram


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
    ("stage",),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 40, 60),
)
_TOKENS = Counter(
    "pi_rag_tokens_total",
    "LLM and embedding token usage.",
    ("stage", "direction", "model_provider", "model_name", "model_profile"),
)
_RETRIES = Counter(
    "pi_rag_retries_total", "Transient and semantic RAG retries.", ("stage",)
)
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
    if value and len(value) <= 128 and all(character.isalnum() or character in "-_." for character in value):
        return value
    return str(uuid.uuid4())


def set_request_id(value: str) -> object:
    return _REQUEST_ID.set(value)


def reset_request_id(token: object) -> None:
    _REQUEST_ID.reset(token)  # type: ignore[arg-type]


def request_id() -> str:
    return _REQUEST_ID.get()


def started() -> float:
    return time.perf_counter()


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
    extra: dict[str, int | float | str] | None = None,
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
    _STAGE_DURATION.labels(stage).observe(duration_seconds)
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
            count = max(0, int(extra.get(field) or 0))
            if count:
                _RETRIEVAL_CANDIDATES.labels(source_type).inc(count)
        if bool(extra.get("code_required")) and int(extra.get("code_candidates") or 0) == 0:
            _CODE_REQUIRED_ZERO.labels(
                str(extra.get("query_intent") or "DIRECT")
            ).inc()
    if extra and stage == "rerank":
        for source_type, field in (
            ("CODE", "code_selected"),
            ("PAGE", "page_selected"),
            ("ISSUE", "issue_selected"),
            ("ATTACHMENT", "attachment_selected"),
        ):
            count = max(0, int(extra.get(field) or 0))
            if count:
                _EVIDENCE_SELECTED.labels(source_type).inc(count)
    if input_tokens:
        _TOKENS.labels(stage, "input", model_provider, model_name, model_profile).inc(input_tokens)
    if output_tokens:
        _TOKENS.labels(stage, "output", model_provider, model_name, model_profile).inc(output_tokens)
    if retry_count:
        _RETRIES.labels(stage).inc(retry_count)
    LOGGER.info(
        json.dumps(payload, separators=(",", ":"), sort_keys=True)
    )


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
