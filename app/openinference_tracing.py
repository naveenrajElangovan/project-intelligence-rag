"""Failure-isolated OpenInference tracing over the existing OTLP collector.

The exporter is always batched and never sits on the answer critical path.  The
collector routes on ``auth.boundary``; it is responsible for sending a span to
the Phoenix instance that represents that authorization boundary.
"""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings


LOGGER = logging.getLogger("project_intelligence.rag.openinference")


class _BoundarySpanProcessor:
    """Copy request baggage onto every auto-instrumented child span."""

    def on_start(self, span: Any, parent_context: Any = None) -> None:
        from opentelemetry import baggage

        boundary = baggage.get_baggage("auth.boundary", context=parent_context)
        correlation = baggage.get_baggage("request.id", context=parent_context)
        if boundary:
            span.set_attribute("auth.boundary", str(boundary))
        if correlation:
            span.set_attribute("request.id", str(correlation))

    def on_end(self, span: Any) -> None:
        del span

    def _on_ending(self, span: Any) -> None:
        """Support SDKs that notify processors immediately before ``Span.end``."""

        del span

    def shutdown(self) -> None:
        return None

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        del timeout_millis
        return True


def configure_openinference(settings: Settings) -> Any | None:
    if not settings.openinference_enabled:
        return None

    from openinference.instrumentation import TraceConfig
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    resource_attributes = {
        "service.name": "project-intelligence-rag",
        "service.namespace": "project-intelligence",
        "openinference.project.name": settings.openinference_project_name,
        "rag.success_sample_rate": settings.openinference_success_sample_rate,
    }
    provider = TracerProvider(resource=Resource.create(resource_attributes))
    provider.add_span_processor(_BoundarySpanProcessor())
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.openinference_otlp_endpoint),
            max_queue_size=1024,
            max_export_batch_size=256,
            schedule_delay_millis=2000,
        )
    )
    # Auto-instrumentation never receives blanket content permission: retriever
    # outputs can contain candidates that were not selected for the model. The
    # request/workflow layer emits only server-authorized, selected content.
    privacy = TraceConfig(
        hide_inputs=True,
        hide_outputs=True,
        hide_input_messages=True,
        hide_output_messages=True,
        hide_input_text=True,
        hide_output_text=True,
        hide_embeddings_text=True,
        hide_embeddings_vectors=True,
        hide_llm_invocation_parameters=True,
        hide_llm_tools=True,
        hide_prompts=True,
        hide_choices=True,
    )
    LangChainInstrumentor().instrument(tracer_provider=provider, config=privacy)
    LOGGER.info(
        "OpenInference tracing is enabled with %s content policy.",
        settings.openinference_content_mode,
    )
    return provider
