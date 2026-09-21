from __future__ import annotations
from collections.abc import AsyncIterator
from app.config import Settings
from app.llm import (
    BilingualQueryPlanner,
    ConversationQueryResolver,
    LangChainGroundedAnswerGenerator,
    LangChainSafeResponseGenerator,
)
from app.models import RagRequest, RagResponse
from app.catalog_answers import deterministic_catalog_response
from app.grounding import LocalCitationGroundingVerifier
from app.embedding import build_embedder
from app.reranking import build_reranker
from app.retrieval import ChromaAccessRetriever
from app.vocabulary import CorpusVocabulary
from app.retrieval_pipeline import ReciprocalRankFusion, authorized_project_policies
from app.telemetry import started
from app.workflow_support.json_transform import json_transform_response
from app.workflow_support.execution import invoke_bounded_graph
from app.workflow_support.streaming import graph_update_events, verified_answer_events
from app.workflow_graph import compiled_workflow_graph
from app.workflow_support.citations import (
    _all_material_sentences_cited,
    _citation_failure_reason,
    _citations_valid,
    _material_sentence_count,
    _normalize_citations,
    _normalized_sentence,
    _overview_style_repair_needed,
    _remove_unsupported_claims,
    _answer_without_source_markers,
)
from app.workflow_support.query_analysis import (
    detect_query_language,
    _add_usage,
    _code_inventory_requested,
    _code_location_query,
    _contains_ordered_phrase,
    _document_source_type,
    _entity_overview_entity,
    _entity_overview_source_ids,
    _exact_feature_source_ids,
    _exact_feature_title_match,
    _exact_term_ratio,
    _exact_terms,
    _feature_inventory_entity,
    _feature_title_anchor,
    _identifiers,
    _implementation_evidence_order,
    _intent_source_scope,
    _inventory_documents,
    _low_information_project_document,
    _multi_part_question,
    _normalized_identifier,
    _normalized_words,
    _overview_repair_kwargs,
    _project_overview_evidence_order,
    _project_overview_requested,
    _project_overview_topic,
    _required_evidence_source_types,
    _safe_query_variant,
    _source_authority_valid,
    _source_diverse_order,
    _source_identity,
    _source_route_intent,
    _source_type_count,
)
from app.workflow_support.completeness import (
    _answer_requirements,
    _code_answer_complete,
    _code_output_requested,
    _completeness_repair_query,
    _document_satisfies_requirement,
    _identifier_components,
    _include_repair_evidence,
    _merge_ranked_documents,
    _missing_answer_requirements,
    _missing_evidence_requirements,
    _singular_key,
    _text_satisfies_identifier_requirement,
)
from app.workflow_support.deterministic_answers import (
    _code_inventory_answer_verified,
    _code_inventory_documents,
    _code_inventory_label,
    _code_location_document_score,
    _code_location_label_score,
    _code_location_terms,
    _code_location_values,
    _deterministic_code_inventory_answer,
    _deterministic_code_location_answer,
    _deterministic_delivery_answer,
    _deterministic_feature_inventory_answer,
    _deterministic_identifier_answer,
    _edit_distance_at_most_one,
    _feature_inventory_answer_verified,
    _feature_name_from_title,
    _jira_identifiers,
)
from app.workflow_support.presentation import (
    _expand_candidate_neighbors,
    _stream_progress,
    _answer_deltas,
)
from app.workflow_nodes.answering import AnswerNodesMixin
from app.workflow_nodes.planning import PlanningNodesMixin
from app.workflow_nodes.providers import ProviderNodesMixin
from app.workflow_nodes.retrieval import RetrievalNodesMixin
from app.workflow_nodes.state import RagState
from app.workflow_support.conversation import (
    _conversation_context_subject,
    _conversation_resolution_needed,
    _conversation_subject,
    _deterministic_conversation_rewrite,
    _safe_conversation_rewrite,
)
from app.workflow_support.fail_closed import (
    apply_output_gate,
    clarification_response,
    clarification_response_with_canonical_index,
)
from app.workflow_evaluation import EvaluationWorkflowMixin
from app.workflow_response import WorkflowResponseMixin

__all__ = [
    "AuthorizedRagWorkflow",
    "LangChainSafeResponseGenerator",
    "_add_usage",
    "_all_material_sentences_cited",
    "_answer_deltas",
    "_answer_requirements",
    "_answer_without_source_markers",
    "_citation_failure_reason",
    "_citations_valid",
    "_code_answer_complete",
    "_code_inventory_answer_verified",
    "_code_inventory_documents",
    "_code_inventory_label",
    "_code_inventory_requested",
    "_code_location_document_score",
    "_code_location_label_score",
    "_code_location_query",
    "_code_location_terms",
    "_code_location_values",
    "_code_output_requested",
    "_completeness_repair_query",
    "_contains_ordered_phrase",
    "_conversation_context_subject",
    "_conversation_resolution_needed",
    "_conversation_subject",
    "_deterministic_code_inventory_answer",
    "_deterministic_code_location_answer",
    "_deterministic_conversation_rewrite",
    "_deterministic_delivery_answer",
    "_deterministic_feature_inventory_answer",
    "_deterministic_identifier_answer",
    "_document_satisfies_requirement",
    "_document_source_type",
    "_edit_distance_at_most_one",
    "_entity_overview_entity",
    "_entity_overview_source_ids",
    "_exact_feature_source_ids",
    "_exact_feature_title_match",
    "_exact_term_ratio",
    "_exact_terms",
    "_expand_candidate_neighbors",
    "_feature_inventory_answer_verified",
    "_feature_inventory_entity",
    "_feature_name_from_title",
    "_feature_title_anchor",
    "_identifiers",
    "_identifier_components",
    "_implementation_evidence_order",
    "_include_repair_evidence",
    "_intent_source_scope",
    "_inventory_documents",
    "_jira_identifiers",
    "_low_information_project_document",
    "_material_sentence_count",
    "_merge_ranked_documents",
    "_missing_answer_requirements",
    "_missing_evidence_requirements",
    "_multi_part_question",
    "_normalize_citations",
    "_normalized_identifier",
    "_normalized_sentence",
    "_normalized_words",
    "_overview_repair_kwargs",
    "_overview_style_repair_needed",
    "_project_overview_evidence_order",
    "_project_overview_requested",
    "_project_overview_topic",
    "_remove_unsupported_claims",
    "_required_evidence_source_types",
    "_safe_conversation_rewrite",
    "_safe_query_variant",
    "_singular_key",
    "_source_authority_valid",
    "_source_diverse_order",
    "_source_identity",
    "_source_route_intent",
    "_source_type_count",
    "_stream_progress",
    "_text_satisfies_identifier_requirement",
    "clarification_response",
    "apply_output_gate",
    "detect_query_language",
]


class AuthorizedRagWorkflow(
    WorkflowResponseMixin,
    EvaluationWorkflowMixin,
    ProviderNodesMixin,
    PlanningNodesMixin,
    RetrievalNodesMixin,
    AnswerNodesMixin,
):
    """Bounded graph whose authorization inputs are immutable and never LLM-generated."""

    def __init__(self, settings: Settings, request: RagRequest) -> None:
        if request.retrieval_profile is not None:
            settings = settings.model_copy(update=request.retrieval_profile.settings_overrides())
        self._settings = settings
        self._request = request
        # Keep planning dependencies injectable at this composition boundary.
        self._query_planner_factory = BilingualQueryPlanner
        self._conversation_resolver_factory = ConversationQueryResolver
        required_policy = f"project:{request.project_id}"
        if required_policy not in request.access_policy_ids:
            raise PermissionError("Authorized project policy is required.")
        policies = authorized_project_policies(request.project_id, request.access_policy_ids)
        request = request.model_copy(update={"access_policy_ids": list(policies)})
        self._request = request
        if request.collection_name not in (
            settings.chroma_collection,
            *settings.additional_chroma_collections,
        ):
            raise ValueError(
                "The project collection does not match the configured Chroma collection."
            )
        self._retriever = ChromaAccessRetriever.create(
            chroma_host=settings.chroma_host,
            chroma_port=settings.chroma_port,
            collection_name=request.collection_name,
            text_field=request.text_field,
            project_id=request.project_id,
            access_policy_ids=tuple(dict.fromkeys(request.access_policy_ids)),
            top_k=settings.retrieval_top_k,
            score_threshold=settings.retrieval_score_threshold,
            required_schema_version=request.schema_version,
            required_embedding_model=request.embedding_model,
            retry_attempts=settings.dependency_retry_attempts,
            timeout_seconds=settings.dependency_timeout_seconds,
            lexical_fallback_enabled=settings.lexical_fallback_enabled,
            lexical_fallback_max_records=settings.lexical_fallback_max_records,
            lexical_fallback_cache_ttl_seconds=settings.lexical_fallback_cache_ttl_seconds,
            lexical_fallback_cache_max_entries=settings.lexical_fallback_cache_max_entries,
            vocabulary_cache_ttl_seconds=settings.vocabulary_cache_ttl_seconds,
            embedder=build_embedder(settings),
        )
        self._provider_registry = self._create_provider_registry()
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
        deterministic = deterministic or await deterministic_catalog_response(
            self._request, getattr(self, "_retriever", None)
        )
        if deterministic is not None:
            return deterministic
        clarification = await clarification_response_with_canonical_index(
            self._request,
            self._vocabulary.entities,
            getattr(self._vocabulary, "source_types", ()),
            getattr(self, "_retriever", None),
        )
        if clarification is not None:
            return clarification
        state = await invoke_bounded_graph(
            self._graph,
            {"request": self._request, "_workflow": self},
            project_id=self._request.project_id,
            max_retrieval_attempts=self._settings.max_retrieval_attempts,
            began=began,
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
        deterministic = deterministic or await deterministic_catalog_response(
            self._request, getattr(self, "_retriever", None)
        )
        if deterministic is not None:
            async for event in verified_answer_events(deterministic.answer):
                yield event
            yield {
                "type": "complete",
                "response": deterministic.model_dump(by_alias=True),
            }
            return
        clarification = await clarification_response_with_canonical_index(
            self._request,
            self._vocabulary.entities,
            getattr(self._vocabulary, "source_types", ()),
            getattr(self, "_retriever", None),
        )
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
