"""Final response assembly for the authorized RAG workflow."""

from __future__ import annotations

from typing import cast

from app.config import Settings
from app.llm import (
    RefusalReason,
    TokenUsage,
    insufficient_evidence_answer,
    query_aware_refusal_answer,
    refusal_answer,
)
from app.models import ConversationContextUpdate, RagRequest, RagResponse, SourceReference
from app.quality_tracing import record_selected_evidence
from app.telemetry import request_complete, stage_complete, started
from app.vocabulary import CorpusVocabulary
from app.workflow_nodes.state import RagState
from app.workflow_support.conversation import build_conversation_context_update
from app.workflow_support.fail_closed import resolved_request_for_state
from app.workflow_support.presentation import _degradation_reasons, _highest_rerank_score
from app.workflow_support.query_analysis import _dedupe_source_documents, resolve_response_language


class WorkflowResponseMixin:
    """Assemble public responses from the graph's final private state."""

    _request: RagRequest
    _settings: Settings
    _vocabulary: CorpusVocabulary

    async def _response_from_state(self, state: RagState, began: float) -> RagResponse:
        """Convert final graph state into an audited public response."""
        # Resolve these through the long-standing composition-module boundary so
        # dependency injection and tests can replace them without knowing this
        # implementation detail moved to a cohesive submodule.
        from app import workflow as workflow_module

        provider_response = state.get("provider_response")
        if provider_response is not None:
            request_complete(
                began=began,
                outcome="ANSWERED" if provider_response.status == "ANSWERED" else "NO_ANSWER",
                confidence=provider_response.confidence,
                model_profile=self._request.model_profile,
                language=resolve_response_language(
                    self._request.question, default=self._settings.default_response_language
                ),
                reason_code=provider_response.failure_reason or provider_response.resolved_intent,
            )
            return provider_response
        documents = state.get("documents", [])
        record_selected_evidence(documents, self._settings)
        generated = state.get("generated")
        resolved = resolved_request_for_state(state, self._request, self._vocabulary.entities)
        workflow_module.apply_output_gate(state, self._request, resolved, generated)
        generated = state.get("generated")
        if not documents or generated is None or state.get("grounded") is False:
            language = state.get("language") or resolve_response_language(
                self._request.question, default=self._settings.default_response_language
            )
            refusal_began = started()
            refusal = insufficient_evidence_answer(language)
            reason_code = "STATIC_FALLBACK"
            usage = TokenUsage()
            model_provider = "none"
            model_name = "none"
            unverified = (
                bool(documents)
                and state.get("grounded") is False
                and not {state.get("grounding_reason"), state.get("context_quality")}
                & {"INCOMPLETE_EVIDENCE", "INSUFFICIENT"}
            )
            population_miss = bool(state.get("coverage_expected")) and bool(
                state.get("population_retrieval_miss")
            )
            gate_reason = (
                str(state.get("grounding_reason") or "") if state.get("output_gate_applied") else ""
            )
            generated_refusal_reason = (
                generated.refusal_reason
                if generated is not None and generated.outcome == "REFUSAL"
                else None
            )
            refusal_reason = (
                "ENTITY_MISMATCH"
                if state.get("entity_mismatch_requested")
                else generated_refusal_reason
                if generated_refusal_reason
                else gate_reason
                if gate_reason
                in {
                    "UNRESOLVED_SOURCE_CONFLICT",
                    "SOURCE_SCOPE_VIOLATION",
                    "PERMISSIONS_NOT_SATISFIED",
                    "FRESHNESS_NOT_VERIFIABLE",
                    "REQUESTED_COVERAGE_INCOMPLETE",
                    "UNSUPPORTED_CLAIM",
                    "INVALID_DERIVATION",
                    "INSUFFICIENT_ANSWER_SUBSTANCE",
                }
                else "POPULATION_RETRIEVAL_MISS"
                if population_miss
                else "UNVERIFIED_EVIDENCE"
                if unverified
                else "INSUFFICIENT_EVIDENCE"
            )
            refusal = query_aware_refusal_answer(self._request.question, refusal_reason, language)
            if refusal_reason == "ENTITY_MISMATCH":
                requested = str(state.get("entity_mismatch_requested") or "")
                suggested = str(state.get("entity_mismatch_suggested") or "")
                refusal = (
                    f"¿Quisiste decir {suggested} en lugar de {requested}?"
                    if language == "es"
                    else f"Did you mean {suggested} rather than {requested}?"
                )
                reason_code = "ENTITY_MISMATCH"
            try:
                if refusal_reason == "ENTITY_MISMATCH":
                    raise ValueError("deterministic clarification")
                if self._settings.generated_refusals_enabled:
                    responder = workflow_module.LangChainSafeResponseGenerator(
                        self._settings, self._request.model_profile
                    )
                    refusal = await responder.generate(
                        self._request.question,
                        language,
                        cast(RefusalReason, refusal_reason),
                    )
                    usage = responder.last_usage
                    model_provider = self._settings.llm_provider
                    model_name = responder.model_name
                    reason_code = f"GENERATED_{refusal_reason}"
                else:
                    refusal, reason_code = (
                        refusal_answer(refusal_reason, language),
                        f"TEMPLATED_{refusal_reason}",
                    )
            except Exception:
                pass
            stage_complete(
                "generate_safe_response",
                self._request.project_id,
                refusal_began,
                input_count=len(documents),
                output_count=1,
                reason_code=reason_code,
                model_provider=model_provider,
                model_name=model_name,
                model_profile=self._request.model_profile,
                language=language,
                **usage.model_dump(),
            )
            unverified_sources = (
                [
                    SourceReference(
                        type=str(document.metadata.get("source_type") or "DOCUMENT"),
                        title=str(document.metadata.get("title") or "Untitled source"),
                        reference=str(document.metadata.get("reference") or ""),
                        url=str(document.metadata.get("source_url") or "") or None,
                        locator=str(document.metadata.get("locator") or "") or None,
                        language=str(document.metadata.get("language") or "") or None,
                    )
                    for document in _dedupe_source_documents(documents[:3])
                ]
                if unverified
                and refusal_reason not in {"PERMISSIONS_NOT_SATISFIED", "SOURCE_SCOPE_VIOLATION"}
                else []
            )
            response = RagResponse(
                status=(
                    "NEEDS_CLARIFICATION"
                    if refusal_reason == "ENTITY_MISMATCH"
                    else "SOURCE_CONFLICT"
                    if refusal_reason == "UNRESOLVED_SOURCE_CONFLICT"
                    else "ACCESS_DENIED"
                    if refusal_reason == "PERMISSIONS_NOT_SATISFIED"
                    else "INSUFFICIENT_EVIDENCE"
                ),
                answer=refusal,
                confidence="NONE",
                project_id=self._request.project_id,
                sources=unverified_sources,
                missing_information=[],
                evidence_status="UNVERIFIED" if unverified else "INSUFFICIENT",
                context_quality=state.get("context_quality", "INSUFFICIENT"),
                context_relevance=float(state.get("context_relevance", 0.0)),
                context_completeness=float(state.get("context_completeness", 0.0)),
                degradation=_degradation_reasons(state, unverified=unverified),
                refusal_reason=refusal_reason,
                conversation_context_update=None,
                failureReason=refusal_reason,
                resolvedIntent=resolved.intent,
                resolvedEntities=resolved.referenced_entities,
                coverage="PARTIAL" if documents else "NOT_APPLICABLE",
            )
            request_complete(
                began=began,
                outcome="NO_ANSWER",
                confidence="NONE",
                model_profile=self._request.model_profile,
                language=language,
                reason_code=refusal_reason,
            )
            return response
        score = _highest_rerank_score(documents)
        cited_documents = _dedupe_source_documents(
            [
                documents[index - 1]
                for index in dict.fromkeys(generated.citations)
                if 1 <= index <= len(documents)
            ]
        )
        response = RagResponse(
            status="ANSWERED",
            answer=workflow_module._answer_without_source_markers(generated.answer),
            confidence="HIGH" if score >= 0.7 else "MEDIUM",
            project_id=self._request.project_id,
            sources=[
                SourceReference(
                    type=str(document.metadata.get("source_type") or "DOCUMENT"),
                    title=str(document.metadata.get("title") or "Untitled source"),
                    reference=str(document.metadata.get("reference") or ""),
                    url=str(document.metadata.get("source_url") or "") or None,
                    locator=str(document.metadata.get("locator") or "") or None,
                    language=str(document.metadata.get("language") or "") or None,
                )
                for document in cited_documents
            ],
            missing_information=generated.missing_information,
            evidence_status="SUFFICIENT",
            context_quality=state.get("context_quality", "SUFFICIENT"),
            degradation=_degradation_reasons(state),
            context_relevance=float(state.get("context_relevance", score)),
            context_completeness=float(state.get("context_completeness", 1.0)),
            conversation_context_update=self._conversation_context_update(state),
            failureReason=None,
            resolvedIntent=resolved.intent,
            resolvedEntities=resolved.referenced_entities,
            coverage="PARTIAL"
            if state.get("coverage_partial") or generated.missing_information
            else "COMPLETE",
        )
        request_complete(
            began=began,
            outcome="ANSWERED",
            confidence=response.confidence,
            model_profile=self._request.model_profile,
            language=state.get("language", "mixed"),
        )
        return response

    def _conversation_context_update(self, state: RagState) -> ConversationContextUpdate:
        """Return bounded semantic memory without promoting chat text to evidence."""
        entities = tuple(getattr(getattr(self, "_vocabulary", None), "entities", ()) or ())
        return build_conversation_context_update(self._request, state, entities)
