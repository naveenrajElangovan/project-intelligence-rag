from __future__ import annotations

import re

from app.llm import BilingualQueryPlanner, ConversationQueryResolver, TokenUsage
from app.telemetry import stage_complete, started
from app.workflow_nodes.state import RagState
from app.workflow_support.conversation import (
    _bounded_history,
    _conversation_resolution_decision,
    _conversation_subject,
    _deterministic_conversation_rewrite,
    _resolved_conversation_subject,
    _safe_conversation_rewrite,
)
from app.workflow_support.query_analysis import (
    _code_inventory_requested,
    _entity_overview_entity,
    _feature_inventory_entity,
    _intent_source_scope,
    _multi_part_question,
    _project_overview_requested,
    _safe_query_variant,
    _source_route_intent,
    _query_quality,
    _code_location_query,
    detect_query_language,
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


class PlanningNodesMixin:
    """PlanningNodes responsibilities."""

    async def _plan_queries(self, state: RagState) -> RagState:
        """Resolve bounded follow-ups, classify intent, and create retrieval queries."""

        began = started()
        original_question = self._request.question
        language = detect_query_language(original_question)
        question = await self._resolve_conversation_question(original_question, language)
        query_quality, quality_reason = _query_quality(question)
        detected_language = language
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
        reason_code = "DIRECT_RETRIEVE_FIRST"
        usage = TokenUsage()
        # Retrieval-first avoids an LLM round trip for ordinary direct questions.
        # Spanish translation and true multi-part decomposition justify one bounded
        # planner call because they materially improve recall before generation.
        needs_planner = (
            detected_language == "es" and self._settings.translation_enabled
        ) or (
            self._settings.adaptive_query_enabled
            and self._settings.query_expansion_enabled
            and (
                query_quality != "GOOD"
                or _multi_part_question(question)
                or _code_location_query(question)
            )
        )
        if needs_planner:
            try:
                planner = self._query_planner_factory(
                    self._settings, self._request.model_profile
                )
                plan = await planner.plan(question)
                usage = planner.last_usage
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
                            usage = TokenUsage(
                                input_tokens=usage.input_tokens + planner.last_usage.input_tokens,
                                output_tokens=usage.output_tokens + planner.last_usage.output_tokens,
                                cached_tokens=usage.cached_tokens + planner.last_usage.cached_tokens,
                                reasoning_tokens=usage.reasoning_tokens + planner.last_usage.reasoning_tokens,
                                retry_count=usage.retry_count + planner.last_usage.retry_count,
                            )
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
            extra={"query_intent": query_intent, "source_route": source_route},
            **usage.model_dump(),
        )
        return {
            "queries": planned,
            "language": language,
            "retrieval_attempt": 1,
            "query_intent": query_intent,
            "rerank_query": rerank_query,
            "source_types": source_types,
            "source_route": source_route,
            "resolved_question": question,
            "query_quality": query_quality,
            "query_quality_reason": quality_reason,
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
        resolution_needed, predicate_reason = _conversation_resolution_decision(question)
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
        if _conversation_subject(question):
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
        # Rewording cannot rescue a wrong route. A source scope that returned no
        # candidates at all is a routing failure, not a phrasing failure, and
        # retrying the same scope with new words returns nothing a second time.
        # Widen to every source type the corpus actually holds, and drop back to
        # the default route so the answer contract and the required-evidence check
        # match the widened evidence. Which source types exist is read from the
        # project vocabulary, so no source name is hardcoded here.
        scoped = tuple(
            str(source_type).upper() for source_type in state.get("source_types", ())
        )
        available = tuple(
            str(source_type).upper()
            for source_type in getattr(self._vocabulary, "source_types", ())
        )
        widen_scope = (
            not state.get("documents")
            and bool(scoped)
            and bool(set(available) - set(scoped))
        )
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
        if widen_scope:
            # Reuse the original question when the planner produced no variant:
            # the words were never the problem, the scope was.
            if not query:
                recovered["queries"] = (self._request.question,)
            recovered["source_types"] = ()
            recovered["source_route"] = "MIXED"
            recovered["query_intent"] = "CODE_ASSISTED"
            recovered["source_scope_widened"] = True
        return recovered
