"""Privacy-safe OpenInference tracing over the existing OTLP collector."""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings


LOGGER = logging.getLogger("project_intelligence.rag.openinference")


def configure_openinference(settings: Settings) -> Any | None:
    if not settings.openinference_enabled:
        return None

    from openinference.instrumentation import TraceConfig
    from openinference.instrumentation.langchain import LangChainInstrumentor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider(
        resource=Resource.create(
            {
                "service.name": "project-intelligence-rag",
                "service.namespace": "project-intelligence",
                "openinference.project.name": "project-intelligence-rag",
            }
        )
    )
    provider.add_span_processor(
        BatchSpanProcessor(
            OTLPSpanExporter(endpoint=settings.openinference_otlp_endpoint),
            max_queue_size=1024,
            max_export_batch_size=256,
            schedule_delay_millis=2000,
        )
    )
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
    LOGGER.info("Privacy-safe OpenInference tracing is enabled.")
    return provider
