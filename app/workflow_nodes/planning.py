from __future__ import annotations

import re

from app.llm import BilingualQueryPlanner, ConversationQueryResolver, TokenUsage
from app.telemetry import stage_complete, started
from app.grounding_contract import resolve_request
from app.source_policy import SourcePolicyRegistry
from app.workflow_support.identifiers import member_identifiers
from app.workflow_support.inventory_intent import is_exhaustive_entity_detail_question
from app.workflow_support.language import resolve_conversation_response_language
from app.workflow_nodes.state import RagState
from app.workflow_support.conversation import (
    _bounded_history,
    conversation_anchor_terms,
    _contextual_subtopic_followup,
    _conversation_resolution_decision,
    _conversation_subject,
    _deterministic_conversation_rewrite,
    _resolved_conversation_subject,
    _safe_conversation_rewrite,
    _subject_matches_vocabulary,
)
from app.workflow_support.query_analysis import (
    _code_inventory_requested,
    _entity_overview_entity,
    _feature_inventory_entity,
    _intent_source_scope,
    _multi_part_question,
    _project_overview_requested,
    _safe_query_variant,
    _safe_translation_variant,
    _source_route_intent,
    _query_quality,
    autocorrect_question,
    _code_location_query,
    corrected_query_variant,
    retrieval_terminology_variant,
    uncertain_entity_token,
)


def _combined_usage(first: TokenUsage, second: TokenUsage) -> TokenUsage:
    return TokenUsage(
        input_tokens=first.input_tokens + second.input_tokens,
        output_tokens=first.output_tokens + second.output_tokens,
        cached_tokens=first.cached_tokens + second.cached_tokens,
        reasoning_tokens=first.reasoning_tokens + second.reasoning_tokens,
        retry_count=first.retry_count + second.retry_count,
    )


def _implementation_flow_requested(value: str) -> bool:
    """Recognize questions whose answer may span documentation and source code."""

    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    asks_for_mechanism = bool(
        re.search(
            r"\b(?:how|where|which|what|como|donde|cual|que)\b",
            normalized,
        )
    )
    implementation_signal = bool(
        re.search(
            r"\b(?:implement(?:ed|ation)?|validat(?:e|es|ed|ing|ion)?|"
            r"authenticat(?:e|es|ed|ing|ion)?|login|logins|password|passwords|"
            r"credential|credentials|workflow|call flow|code flow|works|handled)\b",
            normalized,
        )
    )
    return asks_for_mechanism and implementation_signal


def _implementation_flow_queries(question: str) -> tuple[str, ...]:
    """Build deterministic cross-source variants without inventing identifiers."""

    variants = [
        question,
        f"{question} implementation source code classes functions use case repository",
        f"{question} workflow call flow validation documentation",
    ]
    if re.search(
        r"\b(?:login|logins|password|passwords|credential|credentials|auth|authentication)\b",
        question,
        flags=re.IGNORECASE,
    ):
        variants[-1] = (
            f"{question} authentication login credential validation service viewmodel usecase"
        )
    return tuple(variants)


def _structured_inventory_requested(value: str) -> bool:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    return bool(
        re.search(
            r"\b(?:list|show|give|provide|return|enumerate|inventory|catalog|"
            r"catalogue|need|want|request)\b",
            normalized,
        )
        and re.search(r"\b(?:all|every|complete|full)\b", normalized)
    )


def _structured_inventory_subject(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    subject = re.sub(
        r"\b(?:can|could|would|you|please|me|i|list|show|give|provide|return|"
        r"enumerate|need|want|request|all|every|complete|full|inventory|catalog|"
        r"catalogue|the|a|an|of|in|from|for|with|details|only)\b",
        " ",
        normalized,
    )
    return re.sub(r"\s+", " ", subject).strip(" ?.,") or normalized


def _single_record_details_requested(value: str) -> bool:
    """Recognize a request for one complete example without making it exhaustive."""

    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    return bool(
        re.search(
            r"\b(?:send|give|show|provide|return|select|choose|dame|muestra)\b",
            normalized,
        )
        and re.search(r"\b(?:one|single|example|sample|uno|una)\b", normalized)
        and re.search(
            r"\b(?:full|complete|details?|record|schema|fields?|"
            r"completo|completa|detalles?|registro|campos?)\b",
            normalized,
        )
    )


def _single_record_subject(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value).strip().casefold()
    subject = re.sub(
        r"\b(?:can|could|would|you|please|me|send|give|show|provide|return|"
        r"select|choose|one|single|example|sample|full|complete|details?|the|"
        r"a|an|of|in|from|for|with)\b",
        " ",
        normalized,
    )
    return re.sub(r"\s+", " ", subject).strip(" ?.,") or normalized


def _entity_attribute_value_requested(value: str) -> bool:
    """Recognize how a named entity's field is populated at runtime."""

    return bool(
        member_identifiers(value)
        and re.search(
            r"\b(?:field|property|parameter|attribute|status|value|campo|propiedad|"
            r"parametro|parámetro|estado|valor)\b",
            value,
            re.IGNORECASE,
        )
        and re.search(
            r"\b(?:pass|passes|passed|passing|set|sets|assigned|populate|populated|"
            r"send|sent|contain|contains|will|what|which|how|pasa|asigna|envia|envía)\b",
            value,
            re.IGNORECASE,
        )
    )


class PlanningNodesMixin:
    """PlanningNodes responsibilities."""

    async def _plan_queries(self, state: RagState) -> RagState:
        planned = await self._plan_queries_core(state)
        source_types = planned.get("source_types", ())
        if not source_types:
            source_types = tuple(
                str(value).upper()
                for value in getattr(self._vocabulary, "source_types", ())
                if str(value).strip()
            )
        registry = SourcePolicyRegistry.from_categories(
            (*getattr(self._vocabulary, "source_types", ()), *source_types)
        )
        selected = registry.select(
            planned.get("query_intent", "DIRECT"), source_types
        )
        planned["resolved_request"] = resolve_request(
            planned.get("resolved_question", self._request.question),
            intent=planned.get("query_intent", "DIRECT"),
            allowed_source_categories=selected,
            known_entities=getattr(self._vocabulary, "entities", ()),
        )
        return planned

    async def _plan_queries_core(self, state: RagState) -> RagState:
        """Resolve bounded follow-ups, classify intent, and create retrieval queries."""

        began = started()
        # Correct the question once, here, so every downstream consumer -- language
        # detection, conversation resolution, intent routing and the retrieval
        # queries -- sees the same repaired text. Correction is dictionary-bounded
        # and never touches identifiers, acronyms or project entities.
        original_question = autocorrect_question(
            self._request.question,
            vocabulary=getattr(self._vocabulary, "entities", ()),
        )
        history = [
            (message.role, message.content)
            for message in self._request.conversation_history[-6:]
        ]
        language = resolve_conversation_response_language(
            original_question,
            history,
            default=getattr(self._settings, "default_response_language", "es"),
        )
        question = await self._resolve_conversation_question(original_question, language)
        query_quality, quality_reason = _query_quality(question)
        detected_language = language
        contextual_parent = (
            _resolved_conversation_subject(question)
            if question != original_question
            and _contextual_subtopic_followup(original_question, history)
            else ""
        )
        if contextual_parent:
            subtopic = original_question.strip().rstrip("?¿!¡.").strip()
            focused_question = (
                f"{subtopic} specifically within {contextual_parent}?"
            )
            query_intent = _source_route_intent(
                focused_question, self._vocabulary.source_types
            )
            source_types, source_route = _intent_source_scope(query_intent)
            planned = (
                focused_question,
                f"{contextual_parent} {subtopic} relationship steps conditions rules",
                f"{contextual_parent} {subtopic} inputs outputs request response implementation",
            )[: self._settings.max_query_variants]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="CONTEXTUAL_SUBTOPIC",
                language=language,
                model_provider="deterministic",
                model_name="contextual-subtopic-planner",
                model_profile="retrieval",
                extra={
                    "query_intent": query_intent,
                    "source_route": source_route,
                },
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": query_intent,
                "rerank_query": focused_question,
                "source_types": source_types,
                "source_route": source_route,
                "resolved_question": focused_question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        if _code_inventory_requested(question):
            planned = (
                question,
                "project source code modules classes functions files tests configuration",
            )[: self._settings.max_query_variants]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="CODE_INVENTORY",
                language=language,
                model_provider="deterministic",
                model_name="code-inventory-planner",
                model_profile="retrieval",
                extra={"query_intent": "CODE_INVENTORY", "source_route": "GITHUB"},
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "CODE_INVENTORY",
                "rerank_query": question,
                "source_types": ("CODE",),
                "source_route": "GITHUB",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        if _single_record_details_requested(
            question
        ) and not is_exhaustive_entity_detail_question(question):
            subject = _single_record_subject(question)
            planned = (
                question,
                f"{subject} complete record fields identifiers values",
                f"{subject} example definition documentation contract",
            )[: self._settings.max_query_variants]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="SINGLE_RECORD_DETAILS",
                language=language,
                model_provider="deterministic",
                model_name="single-record-details-planner",
                model_profile="retrieval",
                extra={"query_intent": "CODE_ASSISTED", "source_route": "MIXED"},
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "CODE_ASSISTED",
                "rerank_query": f"{subject} complete record details",
                "source_types": (),
                "source_route": "MIXED",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
                "reconstruct_parent_records": True,
            }
        if is_exhaustive_entity_detail_question(question):
            identifier = member_identifiers(question)[0]
            semantic_name = " ".join(
                part.casefold()
                for part in identifier.split("_")
                if part.casefold() not in {"event"}
            )
            planned = (
                question,
                f"{identifier} {semantic_name} payload data class fields types SerialName schema",
                f"{identifier} {semantic_name} event constructor assignments contract version wire name",
            )[: self._settings.max_query_variants]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="STRUCTURED_ENTITY_DETAILS",
                language=language,
                model_provider="deterministic",
                model_name="structured-entity-details-planner",
                model_profile="retrieval",
                extra={"query_intent": "STRUCTURED_ENTITY", "source_route": "MIXED"},
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "STRUCTURED_ENTITY",
                "rerank_query": f"{identifier} complete payload fields types",
                "source_types": (),
                "source_route": "MIXED",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        if _entity_attribute_value_requested(question):
            identifier = member_identifiers(question)[0]
            planned = (
                question,
                f"{identifier} payload field property constructor assignment runtime value",
                f"{identifier} event use case populate send enum branch implementation",
            )[: self._settings.max_query_variants]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="ENTITY_ATTRIBUTE_VALUE",
                language=language,
                model_provider="deterministic",
                model_name="entity-attribute-value-planner",
                model_profile="retrieval",
                extra={"query_intent": "IMPLEMENTATION", "source_route": "GITHUB"},
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "IMPLEMENTATION",
                "rerank_query": f"{identifier} payload field runtime assignment implementation",
                "source_types": ("CODE",),
                "source_route": "GITHUB",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        if _structured_inventory_requested(question):
            inventory_subject = _structured_inventory_subject(question)
            inventory_entity = _entity_overview_entity(
                question, self._vocabulary.entities
            ) or _feature_inventory_entity(question, self._vocabulary.entities)
            scope_phrase = f"{inventory_entity} " if inventory_entity else ""
            planned = (
                question,
                f"{scope_phrase}{inventory_subject} complete inventory registry catalog index keys identifiers",
                f"{scope_phrase}{inventory_subject} definitions declarations documentation source code",
            )[: self._settings.max_query_variants]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="STRUCTURED_INVENTORY",
                language=language,
                model_provider="deterministic",
                model_name="structured-inventory-planner",
                model_profile="retrieval",
                extra={
                    "query_intent": "STRUCTURED_INVENTORY",
                    "entity": inventory_entity,
                    "inventory_subject": inventory_subject,
                    "source_route": "MIXED",
                },
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "STRUCTURED_INVENTORY",
                "overview_entity": inventory_entity,
                "rerank_query": f"{scope_phrase}{inventory_subject} complete inventory",
                "source_types": (),
                "source_route": "MIXED",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        if (
            _implementation_flow_requested(question)
            and _source_route_intent(question, self._vocabulary.source_types)
            == "CODE_ASSISTED"
        ):
            planned = _implementation_flow_queries(question)[
                : self._settings.max_query_variants
            ]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="IMPLEMENTATION_FLOW",
                language=language,
                model_provider="deterministic",
                model_name="implementation-flow-planner",
                model_profile="retrieval",
                extra={"query_intent": "CODE_ASSISTED", "source_route": "MIXED"},
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "CODE_ASSISTED",
                "rerank_query": f"{question} implementation workflow source code documentation",
                "source_types": (),
                "source_route": "MIXED",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        inventory_entity = _feature_inventory_entity(question, self._vocabulary.entities)
        if inventory_entity:
            entity = inventory_entity.upper()
            planned = (
                question,
                f"{entity} feature documentation",
                f"{entity} application modules capabilities workflows",
            )[: self._settings.max_query_variants]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="FEATURE_INVENTORY",
                language=language,
                model_provider="deterministic",
                model_name="feature-inventory-planner",
                model_profile="retrieval",
                extra={"query_intent": "FEATURE_INVENTORY", "entity": entity},
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "FEATURE_INVENTORY",
                "overview_entity": inventory_entity,
                "rerank_query": f"{entity} application feature documentation",
                "source_types": ("PAGE",),
                "source_route": "CONFLUENCE",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        # For an ambiguous follow-up, classify the carried subject itself. The
        # conversational wording ("yes, specifically", "tell me more") must not
        # dilute a clear product/entity established by the previous turn.
        carried_subject = (
            _resolved_conversation_subject(question)
            if question != original_question
            else ""
        )
        overview_entity = _entity_overview_entity(
            carried_subject, self._vocabulary.entities
        ) or _entity_overview_entity(question, self._vocabulary.entities)
        if overview_entity:
            entity = overview_entity.upper()
            planned = (
                question,
                f"{entity} application overview",
                f"{entity} features workflows architecture",
            )[: self._settings.max_query_variants]
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="ENTITY_OVERVIEW",
                language=language,
                model_provider="deterministic",
                model_name="entity-overview-planner",
                model_profile="retrieval",
                extra={"query_intent": "ENTITY_OVERVIEW", "entity": entity},
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "ENTITY_OVERVIEW",
                "overview_entity": overview_entity,
                "rerank_query": f"{entity} application overview features workflows architecture",
                "source_types": ("PAGE",),
                "source_route": "CONFLUENCE",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        if _project_overview_requested(question, self._request.project_id):
            project = self._request.project_id
            entity_queries = tuple(
                f"{entity} application overview features workflows architecture"
                for entity in self._vocabulary.entities[
                    : self._settings.max_entity_expansions
                ]
            )
            planned = (
                question,
                *(f"{project} {query}" for query in entity_queries),
                f"{project} architecture integrations platform",
            )[: self._settings.max_query_variants]
            project_rerank_queries = (
                *entity_queries,
                f"{project} architecture integrations platform",
            )
            stage_complete(
                "plan_queries",
                self._request.project_id,
                began,
                input_count=1,
                output_count=len(planned),
                reason_code="PROJECT_OVERVIEW",
                language=language,
                model_provider="deterministic",
                model_name="project-overview-planner",
                model_profile="retrieval",
                extra={
                    "query_intent": "PROJECT_OVERVIEW",
                    "entity_vocabulary_size": len(self._vocabulary.entities),
                    "entity_capability": (
                        "enabled" if self._vocabulary.entities else "disabled"
                    ),
                },
            )
            return {
                "queries": planned,
                "language": language,
                "retrieval_attempt": 1,
                "query_intent": "PROJECT_OVERVIEW",
                "rerank_query": f"{project} project applications features architecture integrations",
                "project_rerank_queries": project_rerank_queries,
                "source_types": (),
                "source_route": "MIXED",
                "resolved_question": question,
                "query_quality": query_quality,
                "query_quality_reason": quality_reason,
            }
        query_intent = _source_route_intent(
            question, self._vocabulary.source_types
        )
        source_types, source_route = _intent_source_scope(query_intent)
        queries = [question]
        rerank_queries = [question]
        # A follow-up inherits the previous subject but not the identifiers the
        # previous answer introduced, so a question about codes that answer named
        # retrieved on the bare codes and found nothing. Only fires when the
        # resolver actually rewrote the question, so a standalone question is
        # never polluted by the turn before it.
        if question != original_question:
            anchor_terms = conversation_anchor_terms(history, original_question)
            if anchor_terms:
                anchored = f"{question} {' '.join(anchor_terms)}"
                if anchored not in queries:
                    queries.append(anchored)
                    rerank_queries.append(anchored)
        reason_code = "DIRECT_RETRIEVE_FIRST"
        usage = TokenUsage()
        corrected = corrected_query_variant(question, self._vocabulary.entities)
        uncertain_entity = uncertain_entity_token(question, self._vocabulary.entities)
        if corrected and _safe_query_variant(question, corrected):
            queries.append(corrected)
            rerank_queries.append(corrected)
            terminology = retrieval_terminology_variant(corrected)
            if uncertain_entity:
                terminology = re.sub(
                    rf"(?<![A-Za-z0-9_]){re.escape(uncertain_entity)}(?![A-Za-z0-9_])",
                    "",
                    terminology or corrected,
                    flags=re.IGNORECASE,
                )
                terminology = re.sub(r"\s+", " ", terminology).strip()
            if terminology and _safe_query_variant(question, terminology):
                queries.append(terminology)
                rerank_queries.append(terminology)
            reason_code = "NOISY_QUERY_NORMALIZED"
        planner = None
        translation_used = False
        # Both directions, not just Spanish->English. The corpus is bilingual, so
        # whichever language the question arrives in, the other one has to be
        # offered to retrieval or the reranker is asked to match across a gap it
        # cannot close on its own.
        if detected_language in ("es", "en") and self._settings.translation_enabled:
            try:
                planner = self._query_planner_factory(
                    self._settings, self._request.model_profile
                )
                translated = (
                    await planner.translate_to_english(question)
                    if detected_language == "es"
                    else await planner.translate_to_spanish(question)
                )
                usage = _combined_usage(usage, planner.last_usage)
                if (
                    _safe_translation_variant(
                        question, translated, self._vocabulary.entities
                    )
                    and translated not in queries
                ):
                    queries.append(translated)
                    rerank_queries.append(translated)
                    terminology = retrieval_terminology_variant(translated)
                    if terminology and _safe_translation_variant(
                        question, terminology, self._vocabulary.entities
                    ):
                        queries.append(terminology)
                        rerank_queries.append(terminology)
                    translation_used = True
                    reason_code = "DIRECT_WITH_TRANSLATION"
            except Exception:
                reason_code = "TRANSLATION_FALLBACK"
        # Retrieval-first avoids an LLM round trip for ordinary direct questions.
        # Spanish translation and true multi-part decomposition justify one bounded
        # planner call because they materially improve recall before generation.
        needs_planner = (
            (detected_language == "es" and not translation_used)
            or (
            self._settings.adaptive_query_enabled
            and self._settings.query_expansion_enabled
            and (
                query_quality != "GOOD"
                or _multi_part_question(question)
                or _code_location_query(question)
            )
            )
        )
        if needs_planner:
            try:
                planner = planner or self._query_planner_factory(
                    self._settings, self._request.model_profile
                )
                plan = await planner.plan(question)
                usage = _combined_usage(usage, planner.last_usage)
                for candidate in (*plan.search_queries, plan.translated_query):
                    if (
                        _safe_query_variant(question, candidate)
                        and candidate not in queries
                    ):
                        queries.append(candidate)
                if (
                    self._settings.hyde_enabled
                    and query_quality != "GOOD"
                    and len(queries) < self._settings.max_query_variants
                ):
                    try:
                        hypothesis = await planner.hyde(question)
                        if _safe_query_variant(question, hypothesis) and hypothesis not in queries:
                            queries.append(hypothesis)
                            usage = _combined_usage(usage, planner.last_usage)
                    except Exception:
                        pass
                if len(queries) > 1:
                    reason_code = (
                        "MULTI_PART_SPLIT"
                        if _multi_part_question(question)
                        else "DIRECT_WITH_TRANSLATION"
                    )
            except Exception:
                reason_code = "PLANNER_FALLBACK"
        planned = tuple(queries[: self._settings.max_query_variants])
        # The multilingual cross-encoder must score against the user's original
        # wording. English translations remain retrieval expansions, but using
        # them for final reranking can demote an exact Spanish symptom heading in
        # favor of a generic English sibling section.
        rerank_query = question
        stage_complete(
            "plan_queries",
            self._request.project_id,
            began,
            input_count=1,
            output_count=len(planned),
            reason_code=reason_code,
            language=language,
            model_provider=self._settings.llm_provider,
            model_name=self._settings.ollama_planner_model if self._settings.llm_provider == "ollama" else self._settings.model_for_profile(self._request.model_profile),
            model_profile=self._request.model_profile,
            extra={
                "query_intent": query_intent,
                "source_route": source_route,
                "translation_used": translation_used,
                "corrected_variant_used": bool(corrected),
            },
            **usage.model_dump(),
        )
        return {
            "queries": planned,
            "language": language,
            "retrieval_attempt": 1,
            "query_intent": query_intent,
            "rerank_query": rerank_query,
            "rerank_queries": tuple(dict.fromkeys(rerank_queries)),
            "source_types": source_types,
            "source_route": source_route,
            "resolved_question": question,
            "query_quality": query_quality,
            "query_quality_reason": quality_reason,
            "uncertain_entity_token": uncertain_entity,
        }

    async def _resolve_conversation_question(
        self, question: str, language: str
        ) -> str:
        """Rewrite only ambiguous follow-ups; direct questions incur no model call."""

        history = _bounded_history(
            [
                (message.role, message.content)
                for message in self._request.conversation_history[-6:]
            ],
            self._settings.max_conversation_history_tokens,
        )
        began = started()
        vocabulary = tuple(
            getattr(getattr(self, "_vocabulary", None), "entities", ()) or ()
        )
        resolution_needed, predicate_reason = _conversation_resolution_decision(
            question, vocabulary or None
        )
        if not resolution_needed and _contextual_subtopic_followup(question, history):
            resolution_needed = True
            predicate_reason = "CONTEXTUAL_SUBTOPIC"
        if not resolution_needed:
            stage_complete(
                "resolve_conversation",
                self._request.project_id,
                began,
                input_count=len(history) + 1,
                output_count=1,
                reason_code="CONVERSATION_NOT_REQUIRED",
                language=language,
                model_provider="deterministic",
                model_name="conversation-followup-predicate",
                model_profile=self._request.model_profile,
                extra={
                    "history_message_count": len(history),
                    "predicate_result": False,
                    "predicate_reason": predicate_reason,
                },
            )
            return question
        # A new explicit subject wins even when the sentence also contains a
        # pronoun (for example, "How does authentication work and where is it used?").
        # When the project publishes a vocabulary, require the extracted subject
        # to overlap it. Otherwise formatting phrases in referential requests can
        # masquerade as subjects and replace the active conversation topic.
        candidate_subject = _conversation_subject(question)
        explicit_subject = bool(candidate_subject)
        if candidate_subject and vocabulary:
            explicit_subject = _subject_matches_vocabulary(
                candidate_subject, vocabulary
            )
        if explicit_subject and predicate_reason != "CONTEXTUAL_SUBTOPIC":
            stage_complete(
                "resolve_conversation",
                self._request.project_id,
                began,
                input_count=len(history) + 1,
                output_count=1,
                reason_code="CONVERSATION_EXPLICIT_SUBJECT",
                language=language,
                model_provider="deterministic",
                model_name="conversation-followup-predicate",
                model_profile=self._request.model_profile,
                extra={
                    "history_message_count": len(history),
                    "predicate_result": True,
                    "predicate_reason": predicate_reason,
                },
            )
            return question
        stored_subject = self._request.conversation_context.active_subject.strip()
        # Re-normalize persisted subjects so conversations created by an older
        # deployment shed greetings and conversational filler automatically.
        active_subject = _conversation_subject(stored_subject) or stored_subject
        if not history and not active_subject:
            stage_complete(
                "resolve_conversation",
                self._request.project_id,
                began,
                input_count=1,
                output_count=1,
                reason_code="CONVERSATION_CONTEXT_UNAVAILABLE",
                language=language,
                model_provider="deterministic",
                model_name="conversation-followup-predicate",
                model_profile=self._request.model_profile,
                extra={
                    "history_message_count": 0,
                    "predicate_result": True,
                    "predicate_reason": predicate_reason,
                },
            )
            return question
        resolved = (
            f"{question.rstrip()} (previous subject: {active_subject})"
            if active_subject
            else None
            if predicate_reason == "SHORT_VERB_ELLIPSIS"
            else _deterministic_conversation_rewrite(question, history, language)
        )
        reason_code = (
            "CONVERSATION_REFERENCE_RESOLVED"
            if resolved is not None
            else "CONVERSATION_REWRITE_REJECTED"
        )
        usage = TokenUsage()
        if resolved is None:
            resolved = question
            try:
                resolver = self._conversation_resolver_factory(
                    self._settings, self._request.model_profile
                )
                candidate = await resolver.resolve(question, history, language)
                usage = resolver.last_usage
                if _safe_conversation_rewrite(question, candidate, history):
                    resolved = candidate
                    reason_code = "CONVERSATION_FOLLOWUP_RESOLVED"
            except Exception:
                reason_code = "CONVERSATION_REWRITE_FALLBACK"
        deterministic = reason_code == "CONVERSATION_REFERENCE_RESOLVED"
        stage_complete(
            "resolve_conversation",
            self._request.project_id,
            began,
            input_count=len(history) + 1,
            output_count=1,
            reason_code=reason_code,
            language=language,
            model_provider="deterministic" if deterministic else self._settings.llm_provider,
            model_name=(
                "conversation-reference-resolver"
                if deterministic
                else self._settings.ollama_planner_model
                if self._settings.llm_provider == "ollama"
                else self._settings.model_for_profile(self._request.model_profile)
            ),
            model_profile=self._request.model_profile,
            extra={
                "history_message_count": len(history),
                "semantic_context_used": bool(active_subject),
                "context_state_revision": self._request.conversation_context.state_revision,
                "predicate_result": True,
                "predicate_reason": predicate_reason,
            },
            **usage.model_dump(),
        )
        return resolved

    async def _recover_query(self, state: RagState) -> RagState:
        began = started()
        planner = self._query_planner_factory(
            self._settings, self._request.model_profile
        )
        query = ""
        reason_code = "RECOVERY_QUERY_REJECTED"
        try:
            candidate = await planner.recover(self._request.question, state["queries"])
            if _safe_query_variant(self._request.question, candidate) and candidate not in state["queries"]:
                query = candidate
                reason_code = "RECOVERY_QUERY_CREATED"
        except Exception:
            reason_code = "RECOVERY_PLANNER_FAILED"
        usage = planner.last_usage
        # A recovery query may improve wording but may never broaden the source
        # policy selected during request resolution. An empty result is evidence
        # insufficiency inside that scope, not permission to search elsewhere.
        scoped = tuple(
            str(source_type).upper() for source_type in state.get("source_types", ())
        )
        available = tuple(
            str(source_type).upper()
            for source_type in getattr(self._vocabulary, "source_types", ())
        )
        widen_scope = False
        stage_complete(
            "recover_query",
            self._request.project_id,
            began,
            input_count=len(state["queries"]),
            output_count=1 if query else 0,
            reason_code=reason_code,
            model_provider=self._settings.llm_provider,
            model_name=planner.model_name,
            model_profile=self._request.model_profile,
            language=state.get("language", "und"),
            extra={
                "source_scope_widened": widen_scope,
                "scoped_source_types": ",".join(scoped),
                "available_source_types": ",".join(available),
            },
            **{
                **usage.model_dump(),
                "retry_count": usage.retry_count + (1 if query else 0),
            },
        )
        recovered: RagState = {
            # An empty tuple routes directly to END. Reissuing the question that
            # just returned no evidence only repeats the same expensive rerank.
            "queries": (query,) if query else (),
            "retrieval_attempt": state.get("retrieval_attempt", 1) + 1,
        }
        return recovered
