"""Request-level quality spans with bounded, explicitly authorized content."""

from __future__ import annotations

from contextlib import contextmanager
import re
from typing import Any, Iterator

from opentelemetry import trace
from opentelemetry import baggage, context
from opentelemetry.trace import Status, StatusCode

from app.config import Settings
from app.models import RagRequest, RagResponse
from app.telemetry import request_id


_SECRET_PATTERNS = (
    (re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)((?:api[_-]?key|token|password|cookie)\s*[:=]\s*)[^\s,;]+"), r"\1[REDACTED]"),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]+=*"), "Bearer [REDACTED]"),
)


def redact_trace_text(value: str, *, limit: int = 100_000) -> str:
    """Remove common credential forms and enforce a hard telemetry bound."""

    redacted = value[:limit]
    for pattern, replacement in _SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def _source_payload(response: RagResponse) -> list[dict[str, str | None]]:
    return [
        {
            "type": source.type,
            "title": source.title,
            "reference": source.reference,
            "url": source.url,
            "locator": source.locator,
            "language": source.language,
        }
        for source in response.citations or response.sources
    ]


def record_selected_evidence(documents: list[Any], settings: Settings) -> None:
    """Record identifiers/scores for selected evidence and bodies only by policy."""

    span = trace.get_current_span()
    try:
        for index, document in enumerate(documents):
            metadata = getattr(document, "metadata", {}) or {}
            attributes: dict[str, Any] = {
                "evidence.index": index,
                "evidence.source_id": str(metadata.get("source_id") or metadata.get("id") or ""),
                "evidence.title": str(metadata.get("title") or ""),
                "evidence.locator": str(metadata.get("locator") or metadata.get("structure_path") or ""),
                "evidence.score": float(metadata.get("rerank_score", metadata.get("score", 0.0)) or 0.0),
            }
            if settings.openinference_content_mode == "full_authorized":
                attributes["evidence.body"] = redact_trace_text(
                    str(getattr(document, "page_content", "")), limit=30_000
                )
            span.add_event("rag.selected_evidence", attributes=attributes)
    except Exception:
        return


def record_candidate_scores(documents: list[Any]) -> None:
    """Record every candidate identity and score, never its body."""

    span = trace.get_current_span()
    try:
        for index, document in enumerate(documents):
            metadata = getattr(document, "metadata", {}) or {}
            span.add_event(
                "rag.candidate",
                attributes={
                    "candidate.index": index,
                    "candidate.id": str(metadata.get("chunk_id") or metadata.get("source_id") or metadata.get("id") or ""),
                    "candidate.source_id": str(metadata.get("source_id") or ""),
                    "candidate.dense_score": float(metadata.get("score", 0.0) or 0.0),
                    "candidate.rerank_score": float(metadata.get("rerank_score", 0.0) or 0.0),
                },
            )
    except Exception:
        return


class QualityTrace:
    """A no-throw facade: observability can never fail an answer request."""

    def __init__(self, span: Any, settings: Settings, language: str) -> None:
        self._span = span
        self._settings = settings
        self._language = language

    def response(self, response: RagResponse) -> None:
        try:
            self._span.set_attribute("rag.outcome", response.status.value)
            self._span.set_attribute("rag.confidence", response.confidence)
            self._span.set_attribute("rag.failure_reason", response.failure_reason or "")
            self._span.set_attribute("rag.response_language", self._language)
            self._span.set_attribute("rag.citation_count", len(response.citations))
            if self._settings.openinference_content_mode == "full_authorized":
                import json

                self._span.set_attribute(
                    "output.value", redact_trace_text(response.answer)
                )
                self._span.set_attribute(
                    "rag.selected_evidence",
                    json.dumps(_source_payload(response), ensure_ascii=False),
                )
        except Exception:
            return

    def error(self, failure: BaseException) -> None:
        try:
            self._span.record_exception(failure)
            self._span.set_status(Status(StatusCode.ERROR, type(failure).__name__))
            self._span.set_attribute("rag.outcome", "FAILED")
        except Exception:
            return


@contextmanager
def trace_authorized_request(
    request: RagRequest, settings: Settings, *, streaming: bool, language: str
) -> Iterator[QualityTrace]:
    """Create the boundary-bearing root span after server authorization."""

    tracer = trace.get_tracer("project-intelligence-rag.quality")
    attributes: dict[str, Any] = {
        "openinference.span.kind": "CHAIN",
        "openinference.project.name": settings.openinference_project_name,
        "request.id": request_id(),
        "auth.boundary": f"project:{request.project_id}",
        "rag.project_id": request.project_id,
        "rag.streaming": streaming,
        "rag.model_profile": request.model_profile,
        "rag.embedding_model": request.embedding_model,
        "rag.schema_version": request.schema_version,
        "rag.prompt_version": settings.prompt_version,
        "rag.requested_language": language,
    }
    if settings.openinference_content_mode == "full_authorized":
        attributes["input.value"] = redact_trace_text(request.question)
    baggage_context = baggage.set_baggage("auth.boundary", attributes["auth.boundary"])
    baggage_context = baggage.set_baggage("request.id", attributes["request.id"], baggage_context)
    token = context.attach(baggage_context)
    try:
        with tracer.start_as_current_span("rag.request", attributes=attributes) as span:
            quality = QualityTrace(span, settings, language)
            try:
                yield quality
            except BaseException as failure:
                quality.error(failure)
                raise
    finally:
        context.detach(token)
