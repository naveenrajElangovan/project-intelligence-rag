from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
import re
import unicodedata
from collections.abc import AsyncIterator
from typing import TypedDict

from langchain_core.documents import Document
from app.config import Settings
from app.llm import (BilingualQueryPlanner, ConversationQueryResolver, GroundedAnswer,
                     LangChainGroundedAnswerGenerator, LangChainSafeResponseGenerator,
                     TokenUsage, insufficient_evidence_answer)
from app.models import ConversationContextUpdate, ConversationEntity, RagRequest, RagResponse, SourceReference
from app.grounding import LocalCitationGroundingVerifier
from app.embedding import build_embedder
from app.reranking import build_reranker
from app.retrieval import ChromaAccessRetriever
from app.vocabulary import CorpusVocabulary
from app.retrieval_pipeline import ReciprocalRankFusion
from app.telemetry import request_complete, stage_complete, started
from app.workflow_support.json_transform import json_transform_response
from app.workflow_support.execution import invoke_bounded_graph
from app.workflow_support.streaming import graph_update_events, verified_answer_events
from app.workflow_graph import compiled_workflow_graph
from app.workflow_support.citations import (
    _citations_valid, _remove_unsupported_claims, _normalized_sentence,
    _material_sentence_count,
    _citation_failure_reason,
    _normalize_citations,
    _answer_without_source_markers,
    _all_material_sentences_cited,
    _overview_style_repair_needed,
)
from app.workflow_support.query_analysis import (
    detect_query_language, resolve_response_language,
    _identifiers,
    _safe_query_variant,
    _multi_part_question,
    _exact_terms,
    _exact_term_ratio,
    _add_usage,
    _dedupe_source_documents,
    _source_diverse_order,
    _implementation_evidence_order,
    _inventory_documents,
    _normalized_words,
    _source_route_intent,
    _intent_source_scope,
    _required_evidence_source_types,
    _document_source_type,
    _source_type_count,
    _source_authority_valid,
    _entity_overview_entity,
    _feature_inventory_entity,
    _code_inventory_requested,
    _project_overview_requested,
    _normalized_identifier,
    _low_information_project_document,
    _project_overview_topic,
    _project_overview_evidence_order,
    _overview_repair_kwargs,
    _source_identity,
    _feature_title_anchor,
    _contains_ordered_phrase,
    _exact_feature_title_match,
    _exact_feature_source_ids,
    _entity_overview_source_ids,
    _code_location_query,
)


def _degradation_reasons(state: dict[str, object], *, unverified: bool = False) -> list[str]:
    reasons: list[str] = []
    fallback_count = state.get(
        "fallback_candidate_count", state.get("lexical_fallback_count", 0)
    )
    if int(fallback_count or 0) > 0:
        reasons.append("LEXICAL_RETRIEVAL_FALLBACK")
    if state.get("repaired"):
        reasons.append("GROUNDING_REPAIR")
    if unverified:
        reasons.append("UNVERIFIED_EVIDENCE")
    if state.get("stream_truncated"):
        reasons.append("ANSWER_STREAM_TRUNCATED")
    return reasons
from app.workflow_support.completeness import (
    _answer_requirements,
    _code_answer_complete,
    _code_output_requested,
    _missing_answer_requirements,
    _completeness_repair_query,
    _include_repair_evidence,
    _merge_ranked_documents,
    _document_satisfies_requirement,
    _singular_key,
    _identifier_components,
    _text_satisfies_identifier_requirement,
    _missing_evidence_requirements,
)
from app.workflow_support.deterministic_answers import (
    _deterministic_identifier_answer,
    _deterministic_delivery_answer,
    _jira_identifiers,
    _edit_distance_at_most_one,
    _deterministic_code_location_answer,
    _code_location_terms,
    _code_location_values,
    _code_location_label_score,
    _code_location_document_score,
    _deterministic_feature_inventory_answer,
    _feature_name_from_title,
    _feature_inventory_answer_verified,
    _code_inventory_documents,
    _code_inventory_label,
    _deterministic_code_inventory_answer,
    _code_inventory_answer_verified,
)
from app.workflow_support.presentation import (
    _expand_candidate_neighbors,
    _highest_rerank_score,
    _stream_progress,
    _answer_deltas,
)
from app.workflow_nodes.answering import AnswerNodesMixin
from app.workflow_nodes.planning import PlanningNodesMixin
from app.workflow_nodes.retrieval import RetrievalNodesMixin
from app.workflow_nodes.state import RagState
from app.workflow_support.conversation import (
    _conversation_context_subject,
    _conversation_resolution_needed,
    _conversation_subject,
    _deterministic_conversation_rewrite,
    _safe_conversation_rewrite,
)
from app.workflow_support.fail_closed import apply_output_gate, clarification_response, resolved_request_for_state
from app.workflow_evaluation import EvaluationWorkflowMixin


class AuthorizedRagWorkflow(EvaluationWorkflowMixin, PlanningNodesMixin, RetrievalNodesMixin, AnswerNodesMixin):
    """Bounded graph whose authorization inputs are immutable and never LLM-generated."""
    def __init__(self, settings: Settings, request: RagRequest) -> None:
        self._settings = settings
        self._request = request
        # Keep planning dependencies injectable at this composition boundary.
        self._query_planner_factory = BilingualQueryPlanner
        self._conversation_resolver_factory = ConversationQueryResolver
        required_policy = f"project:{request.project_id}"
        if required_policy not in request.access_policy_ids:
            raise PermissionError("Authorized project policy is required.")
        if request.collection_name != settings.chroma_collection:
            raise ValueError("The project collection does not match the configured Chroma collection.")
        self._retriever = ChromaAccessRetriever.create(
            chroma_host=settings.chroma_host,
            chroma_port=settings.chroma_port,
            collection_name=request.collection_name,
            text_field=request.text_field,
            project_id=request.project_id,
            access_policy_ids=(required_policy,),
            top_k=settings.retrieval_top_k,
            score_threshold=settings.retrieval_score_threshold,
            required_schema_version=request.schema_version,
            required_embedding_model=request.embedding_model,
            retry_attempts=settings.dependency_retry_attempts,
            timeout_seconds=settings.dependency_timeout_seconds,
            lexical_fallback_enabled=settings.lexical_fallback_enabled,
            lexical_fallback_max_records=settings.lexical_fallback_max_records,
            lexical_fallback_cache_ttl_seconds=settings.lexical_fallback_cache_ttl_seconds,
            vocabulary_cache_ttl_seconds=settings.vocabulary_cache_ttl_seconds,
            embedder=build_embedder(settings),
        )
        vocabulary_loader = getattr(self._retriever, "corpus_vocabulary", None)
        self._vocabulary = (
            vocabulary_loader() if vocabulary_loader is not None else CorpusVocabulary()
        )
        self._candidate_fusion = ReciprocalRankFusion(
            k=settings.rank_fusion_k,
            lexical_weight=settings.lexical_fusion_weight,
            dense_weight=settings.dense_fusion_weight,
        )
        self._reranker = build_reranker(settings)
        self._generator = LangChainGroundedAnswerGenerator(settings, request.model_profile)
        self._grounding_verifier = LocalCitationGroundingVerifier(settings)
        self._graph = compiled_workflow_graph()
        self._incremental_stream_active = False

    async def run(self) -> RagResponse:
        """Execute the graph and return one fully verified response."""

        began = started()
        deterministic = json_transform_response(self._request, began)
        if deterministic is not None:
            return deterministic
        clarification = clarification_response(
            self._request, self._vocabulary.entities
        )
        if clarification is not None:
            return clarification
        state = await invoke_bounded_graph(
            self._graph, {"request": self._request, "_workflow": self},
            project_id=self._request.project_id,
            max_retrieval_attempts=self._settings.max_retrieval_attempts, began=began,
        )
        return await self._response_from_state(state, began)

    async def stream(self) -> AsyncIterator[dict[str, object]]:
        """Stream graph progress, then verified answer deltas and final metadata.

        LangGraph node updates are reduced locally and never sent verbatim because
        they contain private evidence. Answer text is released only after the same
        completeness and grounding gates used by :meth:`run` have finished.
        """

        began = started()
        deterministic = json_transform_response(self._request, began)
        if deterministic is not None:
            async for event in verified_answer_events(deterministic.answer):
                yield event
            yield {
                "type": "complete",
                "response": deterministic.model_dump(by_alias=True),
            }
            return
        clarification = clarification_response(self._request, self._vocabulary.entities)
        if clarification is not None:
            async for event in verified_answer_events(clarification.answer):
                yield event
            yield {"type": "complete", "response": clarification.model_dump(by_alias=True)}
            return
        state: RagState = {"request": self._request, "_workflow": self}
        stream_status = {"answer_started": False}
        async for event in graph_update_events(self, state, stream_status):
            yield event
        response = await self._response_from_state(state, began)
        if not stream_status["answer_started"]:
            async for event in verified_answer_events(response.answer):
                yield event
        yield {
            "type": "complete",
            "response": response.model_dump(by_alias=True),
        }

    async def _response_from_state(self, state: RagState, began: float) -> RagResponse:
        """Convert final graph state into an audited public response."""
        documents = state.get("documents", [])
        generated = state.get("generated")
        resolved = resolved_request_for_state(
            state, self._request, self._vocabulary.entities
        )
        apply_output_gate(state, self._request, resolved, generated)
        generated = state.get("generated")
        if not documents or generated is None or state.get("grounded") is False:
            language = state.get("language") or resolve_response_language(self._request.question, default=self._settings.default_response_language)
            refusal_began = started()
            refusal = insufficient_evidence_answer(language)
            reason_code = "STATIC_FALLBACK"
            usage = TokenUsage()
            model_provider = "none"
            model_name = "none"
            # "Nothing was retrieved" and "material was retrieved but the claims
            # written from it could not be verified" are different failures with
            # different fixes -- indexing versus phrasing -- and used to produce
            # the same message, which made the second look like the first.
            unverified = bool(documents) and state.get("grounded") is False and state.get("grounding_reason") != "INCOMPLETE_EVIDENCE"
            population_miss = bool(state.get("coverage_expected")) and bool(
                state.get("population_retrieval_miss")
            )
            gate_reason = str(state.get("grounding_reason") or "") if state.get("output_gate_applied") else ""
            refusal_reason = (
                "ENTITY_MISMATCH"
                if state.get("entity_mismatch_requested")
                else gate_reason
                if gate_reason in {
                    "UNRESOLVED_SOURCE_CONFLICT",
                    "SOURCE_SCOPE_VIOLATION",
                    "PERMISSIONS_NOT_SATISFIED",
                    "FRESHNESS_NOT_VERIFIABLE",
                    "REQUESTED_COVERAGE_INCOMPLETE",
                    "UNSUPPORTED_CLAIM",
                    "INVALID_DERIVATION",
                }
                else "POPULATION_RETRIEVAL_MISS"
                if population_miss
                else "UNVERIFIED_EVIDENCE"
                if unverified
                else "INSUFFICIENT_EVIDENCE"
            )
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
                responder = LangChainSafeResponseGenerator(
                    self._settings, self._request.model_profile
                )
                refusal = await responder.generate(
                    self._request.question, language, refusal_reason
                )
                usage = responder.last_usage
                model_provider = self._settings.llm_provider
                model_name = responder.model_name
                reason_code = f"GENERATED_{refusal_reason}"
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
            # When material was retrieved and only verification failed, naming the
            # pages that were read turns a dead end into a place to look.
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
                and refusal_reason
                not in {"PERMISSIONS_NOT_SATISFIED", "SOURCE_SCOPE_VIOLATION"}
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
            answer=_answer_without_source_markers(generated.answer),
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
            coverage="PARTIAL" if state.get("coverage_partial") or generated.missing_information else "COMPLETE",
        )
        request_complete(
            began=began,
            outcome="ANSWERED",
            confidence=response.confidence,
            model_profile=self._request.model_profile,
            language=state.get("language", "mixed"),
        )
        return response

    def _conversation_context_update(
        self, state: RagState
    ) -> ConversationContextUpdate:
        """Return bounded semantic memory without promoting chat text to evidence."""

        original = self._request.question
        resolved = state.get("resolved_question", original)
        existing = self._request.conversation_context.active_subject.strip()
        vocabulary = tuple(
            getattr(getattr(self, "_vocabulary", None), "entities", ()) or ()
        )
        subject, is_followup = _conversation_context_subject(
            original, resolved, existing, vocabulary
        )
        entities = (
            [ConversationEntity(value=subject, canonicalValue=subject)] if subject else []
        )
        return ConversationContextUpdate(
            standaloneQuestion=resolved,
            activeSubject=subject,
            entities=entities,
            intent=state.get("query_intent", ""),
            resolutionConfidence=1.0 if resolved != original or not is_followup else 0.5,
        )
