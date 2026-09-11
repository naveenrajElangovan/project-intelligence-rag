from __future__ import annotations

import asyncio

from app.models import (
    ConversationContextUpdate,
    ConversationEntity,
    RagResponse,
    ResultPage,
    SourceReference,
    StructuredConversationScope,
)
from app.providers.contracts import ExecutionMode, ProviderName, StructuredOperation
from app.providers.registry import ProviderRegistry
from app.providers.router import select_providers
from app.telemetry import (
    provider_operation,
    stage_complete,
    started,
    structured_context_decision,
)
from app.workflow_nodes.state import RagState
from app.workflow_support.query_analysis import resolve_response_language


def _language(question: str) -> str:
    return resolve_response_language(question, default="en")


def _filter_summary(filters: dict[str, tuple[str, ...]], language: str) -> str:
    values = [value for key, group in filters.items() if key != "fixed" for value in group]
    if not values:
        return ""
    joined = ", ".join(f"**{value}**" for value in values)
    return f" matching {joined}" if language == "en" else f" que coinciden con {joined}"


def _ticket_noun(total: int, language: str) -> str:
    if language == "es":
        return "ticket de Jira" if total == 1 else "tickets de Jira"
    return "Jira ticket" if total == 1 else "Jira tickets"


def _section_label(kind: str | None, language: str) -> str:
    normalized = str(kind or "section").upper()
    if language == "es":
        return {
            "COMMENT": "comentarios",
            "CHANGELOG": "eventos del historial",
            "WORKLOG": "registros de trabajo",
            "ATTACHMENT": "adjuntos",
            "RELATIONSHIP": "relaciones",
            "ACCEPTANCE": "criterios de aceptación",
            "REQUIREMENTS": "requisitos",
            "DESCRIPTION": "descripciones",
            "CUSTOM_FIELD": "campos personalizados",
            "REMOTE_LINK": "enlaces externos",
        }.get(normalized, "secciones")
    return normalized.replace("_", " ").lower() + " records"


def _fixed_rule_text(rule: str | None, language: str) -> str:
    if not rule:
        return ""
    if rule.startswith("RESOLUTION:"):
        value = rule.split(":", 1)[1]
        return (
            f" with Jira resolution {value}"
            if language == "en"
            else f" con resolución de Jira {value}"
        )
    if rule == "STATUS_CATEGORY:DONE":
        return (
            " in Jira's Done status category"
            if language == "en"
            else " en la categoría de estado Done de Jira"
        )
    if rule == "LEGACY_STATUS:DONE":
        return (
            " with legacy Jira status Done"
            if language == "en"
            else " con el estado heredado Done de Jira"
        )
    return ""


def _active_subject(filters: dict[str, tuple[str, ...]], rule: str | None) -> str:
    values = [value for key, group in filters.items() if key != "fixed" for value in group]
    suffix = f"; {rule}" if rule else ""
    return ("Jira tickets" + (f" matching {', '.join(values)}" if values else "") + suffix)[:500]


class ProviderNodesMixin:
    def _create_provider_registry(self) -> ProviderRegistry:
        return ProviderRegistry.indexed(
            project_id=self._request.project_id,
            retriever=self._retriever,
            enabled=tuple(ProviderName(value) for value in self._settings.enabled_providers),
        )

    async def _provider_plan(self, state: RagState) -> RagState:
        began = started()
        configured = self._request.enabled_providers or list(self._settings.enabled_providers)
        enabled = (
            tuple(ProviderName(value) for value in configured)
            if self._settings.provider_router_enabled
            else ()
        )
        scope = (
            self._request.conversation_context.structured_scope
            if self._settings.structured_conversation_enabled
            else None
        )
        selection = select_providers(self._request.question, enabled, scope)
        if scope is not None:
            if selection.reason == "JIRA_STRUCTURED_CONTEXT_INHERITED":
                structured_context_decision("inherited_prevented_legacy_fallback")
            elif selection.mode in {ExecutionMode.LEGACY, ExecutionMode.SINGLE_PROVIDER}:
                structured_context_decision("scope_reset")
            else:
                structured_context_decision("explicit_override")
        if selection.structured_query is not None:
            selection.structured_query.limit = min(
                selection.structured_query.limit,
                self._settings.provider_max_list_items,
            )
        if (
            selection.mode == ExecutionMode.STRUCTURED
            and not self._settings.structured_jira_enabled
        ):
            selection = selection.model_copy(
                update={
                    "mode": ExecutionMode.LEGACY,
                    "reason": "STRUCTURED_JIRA_DISABLED",
                    "structured_query": None,
                }
            )
        if (
            selection.mode == ExecutionMode.FEDERATED
            and not self._settings.provider_federation_enabled
        ):
            selection = selection.model_copy(
                update={
                    "mode": ExecutionMode.LEGACY,
                    "reason": "FEDERATION_DISABLED",
                }
            )
        stage_complete(
            "provider_plan",
            self._request.project_id,
            began,
            input_count=1,
            output_count=len(selection.providers),
            reason_code=selection.reason,
            language=_language(self._request.question),
            model_provider="deterministic",
            model_name="provider-router",
            model_profile="retrieval",
            extra={
                "execution_mode": selection.mode.value,
                "providers": ",".join(selection.providers),
            },
        )
        return {"provider_selection": selection}

    def _route_after_provider_plan(self, state: RagState) -> str:
        selection = state.get("provider_selection")
        if selection and selection.mode == ExecutionMode.STRUCTURED:
            return "structured"
        if selection and selection.mode in {
            ExecutionMode.UNAVAILABLE,
            ExecutionMode.CLARIFICATION,
        }:
            return "unavailable"
        return "legacy"

    async def _provider_unavailable(self, state: RagState) -> RagState:
        selection = state["provider_selection"]
        language = _language(self._request.question)
        if selection.mode == ExecutionMode.CLARIFICATION:
            response = RagResponse(
                status="NEEDS_CLARIFICATION",
                answer=(
                    "Which Jira project, label, or prior ticket set should I apply this to?"
                    if language == "en"
                    else "¿A qué proyecto, etiqueta o conjunto anterior de tickets de Jira debo aplicar esto?"
                ),
                confidence="NONE",
                project_id=self._request.project_id,
                sources=[],
                missing_information=["Jira query scope"],
                evidence_status="INSUFFICIENT",
                context_quality="AMBIGUOUS",
                coverage="NOT_APPLICABLE",
                failure_reason="STRUCTURED_CONTEXT_REQUIRED",
                resolved_intent="JIRA_STRUCTURED_CLARIFICATION",
            )
            structured_context_decision("missing_scope_clarification")
            return {"provider_response": response}
        names = ", ".join(provider.value for provider in selection.providers)
        response = RagResponse(
            status="INSUFFICIENT_EVIDENCE",
            answer=(
                f"The requested provider ({names}) is disabled for this project."
                if language == "en"
                else f"El proveedor solicitado ({names}) está deshabilitado para este proyecto."
            ),
            confidence="NONE",
            project_id=self._request.project_id,
            sources=[],
            missing_information=[f"enabled provider: {names}"],
            evidence_status="INSUFFICIENT",
            context_quality="INSUFFICIENT",
            coverage="NOT_APPLICABLE",
            failure_reason="PROVIDER_DISABLED",
            resolved_intent="PROVIDER_UNAVAILABLE",
        )
        return {"provider_response": response}

    async def _provider_execute(self, state: RagState) -> RagState:
        began = started()
        selection = state["provider_selection"]
        query = selection.structured_query
        if query is None:
            return {}
        adapter = self._provider_registry.get(query.provider)
        try:
            result = await asyncio.wait_for(
                adapter.aggregate(query), timeout=self._settings.provider_timeout_seconds
            )
        except TimeoutError:
            result = None
        language = _language(self._request.question)
        if result is None or not result.complete:
            reason = "PROVIDER_TIMEOUT" if result is None else "INCOMPLETE_PROVIDER_SNAPSHOT"
            response = RagResponse(
                status="INSUFFICIENT_EVIDENCE",
                answer=(
                    "No hay una instantánea completa y autorizada de Jira disponible para calcular un resultado exacto."
                    if language == "es"
                    else "No complete authorized Jira snapshot is available for an exact result."
                ),
                confidence="NONE",
                project_id=self._request.project_id,
                sources=[],
                missing_information=["complete authorized Jira snapshot"],
                evidence_status="INSUFFICIENT",
                context_quality="INSUFFICIENT",
                coverage="PARTIAL",
                failure_reason=reason,
                resolved_intent="JIRA_STRUCTURED_QUERY",
            )
            provider_operation("JIRA", query.operation.value, "incomplete", 0, False)
            stage_complete(
                "provider_execute",
                self._request.project_id,
                began,
                reason_code=reason,
                language=language,
                model_provider="deterministic",
                model_name="jira-aggregate",
                model_profile="retrieval",
            )
            return {"provider_response": response}
        if result.clarification_options:
            structured_context_decision("ambiguous")
            options = ", ".join(result.clarification_options)
            response = RagResponse(
                status="NEEDS_CLARIFICATION",
                answer=(
                    f"Jira has multiple resolutions that could mean fixed ({options}). Which resolution should I use?"
                    if language == "en"
                    else f"Jira tiene varias resoluciones que podrían significar corregido ({options}). ¿Cuál debo usar?"
                ),
                confidence="NONE",
                project_id=self._request.project_id,
                sources=[],
                missing_information=["Jira resolution"],
                evidence_status="INSUFFICIENT",
                context_quality="AMBIGUOUS",
                coverage="NOT_APPLICABLE",
                failure_reason="AMBIGUOUS_JIRA_RESOLUTION",
                resolved_intent="JIRA_STRUCTURED_CLARIFICATION",
            )
            return {"provider_response": response}
        filter_summary = _filter_summary(query.filters, language)
        rule_text = _fixed_rule_text(result.applied_filter_rule, language)
        snapshot = (
            (
                f"\n\n_Data snapshot: {result.snapshot_at}._"
                if language == "en"
                else f"\n\n_Instantánea de datos: {result.snapshot_at}._"
            )
            if result.snapshot_at
            else ""
        )
        if query.operation == StructuredOperation.COUNT:
            ticket_noun = _ticket_noun(result.total, language)
            answer = (
                f"**{result.total} {ticket_noun}**{filter_summary}{rule_text} in **{self._request.project_id}**.{snapshot}"
                if language == "en"
                else f"**{result.total} {ticket_noun}**{filter_summary}{rule_text} en **{self._request.project_id}**.{snapshot}"
            )
        elif query.operation == StructuredOperation.DISTRIBUTION:
            buckets = "\n".join(f"- **{key}:** {value}" for key, value in result.groups.items())
            if not buckets:
                buckets = "- None" if language == "en" else "- Ninguno"
            answer = (
                f"**{result.total} Jira tickets**{filter_summary}{rule_text} in **{self._request.project_id}**.\n\nBreakdown by {query.group_by}:\n{buckets}{snapshot}"
                if language == "en"
                else f"**{result.total} tickets de Jira**{filter_summary}{rule_text} en **{self._request.project_id}**.\n\nDesglose por {query.group_by}:\n{buckets}{snapshot}"
            )
        elif query.operation == StructuredOperation.DETAIL:
            rows = result.rows
            if not rows:
                answer = (
                    f"No matching Jira issue was found in **{self._request.project_id}**.{snapshot}"
                    if language == "en"
                    else f"No se encontró un issue de Jira coincidente en **{self._request.project_id}**.{snapshot}"
                )
            else:
                rendered_details = []
                for row in rows:
                    labels = (
                        ("Estado", "Tipo", "Prioridad", "Responsable", "Reportó", "Fecha límite")
                        if language == "es"
                        else ("Status", "Type", "Priority", "Assignee", "Reporter", "Due date")
                    )
                    fields = [
                        f"**{labels[0]}:** {row['status']}",
                        f"**{labels[1]}:** {row['issue_type']}",
                        f"**{labels[2]}:** {row['priority']}",
                    ]
                    if row.get("assignee"):
                        fields.append(f"**{labels[3]}:** {row['assignee']}")
                    if row.get("reporter"):
                        fields.append(f"**{labels[4]}:** {row['reporter']}")
                    if row.get("due_date"):
                        fields.append(f"**{labels[5]}:** {row['due_date']}")
                    rendered_details.append(
                        f"### {row['key']} — {row['summary']}\n"
                        + "\n".join(f"- {field}" for field in fields)
                    )
                answer = "\n\n".join(rendered_details) + snapshot
        elif query.operation == StructuredOperation.SECTION_COUNT:
            section_kind = _section_label(query.section_kind, language)
            answer = (
                f"**{result.total} indexed Jira {section_kind}** match this authorized scope.{snapshot}"
                if language == "en"
                else f"**{result.total} {section_kind} indexados de Jira** coinciden con este alcance autorizado.{snapshot}"
            )
        elif query.operation == StructuredOperation.SECTION:
            rows = result.rows
            section_kind = _section_label(query.section_kind, language)
            if not rows:
                answer = (
                    f"No indexed Jira {section_kind} match this authorized scope.{snapshot}"
                    if language == "en"
                    else f"No hay registros indexados de {section_kind} de Jira que coincidan con este alcance autorizado.{snapshot}"
                )
            else:
                rendered_sections = []
                for row in rows:
                    heading_bits = [str(row["key"])]
                    if row.get("event_id"):
                        heading_bits.append(f"#{row['event_id']}")
                    if row.get("author"):
                        heading_bits.append(str(row["author"]))
                    if row.get("event_date"):
                        heading_bits.append(str(row["event_date"]))
                    body = str(row.get("text") or "").strip()
                    rendered_sections.append(
                        f"- **{' · '.join(heading_bits)}**\n  {body}"
                        if body
                        else f"- **{' · '.join(heading_bits)}**"
                    )
                start = query.offset + 1
                end = query.offset + len(rows)
                page_text = (
                    f"Showing **{start}–{end} of {result.total}** indexed {section_kind}."
                    if language == "en"
                    else f"Mostrando **{start}–{end} de {result.total}** registros indexados de {section_kind}."
                )
                answer = "\n".join(rendered_sections) + f"\n\n{page_text}{snapshot}"
        else:
            rows = result.rows[: self._settings.provider_max_list_items]
            rendered = "\n".join(
                f"- **{row['key']}** — {row['summary']} · {row['status']}" for row in rows
            )
            returned = len(rows)
            start = query.offset + 1 if returned else min(query.offset, result.total)
            end = query.offset + returned
            if returned:
                ticket_noun = _ticket_noun(result.total, language)
                page_text = (
                    f"Showing **{start}–{end} of {result.total}**."
                    if language == "en"
                    else f"Mostrando **{start}–{end} de {result.total}**."
                )
                answer = (
                    f"Found **{result.total} matching {ticket_noun}**{filter_summary}{rule_text} in **{self._request.project_id}**.\n\n{rendered}\n\n{page_text}{snapshot}"
                    if language == "en"
                    else f"Se encontraron **{result.total} {ticket_noun} coincidentes**{filter_summary}{rule_text} en **{self._request.project_id}**.\n\n{rendered}\n\n{page_text}{snapshot}"
                )
            else:
                answer = (
                    f"There are no more matching Jira tickets. All **{result.total}** results have already been shown.{snapshot}"
                    if language == "en"
                    else f"No hay más tickets de Jira coincidentes. Ya se mostraron los **{result.total}** resultados.{snapshot}"
                )
        sources = [
            SourceReference(
                type="ISSUE",
                title=str(item.document.metadata.get("title") or item.source_id),
                reference=str(item.document.metadata.get("issue_key") or item.source_id),
                url=item.source_url,
                locator=item.locator,
                language=str(item.document.metadata.get("language") or "") or None,
            )
            for item in result.evidence
        ]
        returned = (
            len(result.rows)
            if query.operation in {StructuredOperation.LIST, StructuredOperation.SECTION}
            else 0
        )
        end = query.offset + returned
        subject = _active_subject(query.filters, result.applied_filter_rule)
        context_update = ConversationContextUpdate(
            standaloneQuestion=self._request.question,
            activeSubject=subject,
            entities=[
                ConversationEntity(type="jira_issue_set", value=subject, canonicalValue=subject)
            ],
            intent=f"JIRA_{query.operation.value}",
            resolutionConfidence=1.0,
            structuredScope=StructuredConversationScope(
                provider="JIRA",
                resourceType="ISSUE",
                filters=query.filters,
                operation=query.operation.value,
                groupBy=query.group_by,
                snapshotAt=result.snapshot_at,
                complete=result.complete,
                pageSize=query.limit,
                nextOffset=end,
                activeSubject=subject,
            ),
        )
        result_page = None
        if query.operation in {StructuredOperation.LIST, StructuredOperation.SECTION}:
            result_page = ResultPage(
                start=query.offset + 1 if returned else min(query.offset, result.total),
                end=end,
                returned=returned,
                total=result.total,
                hasMore=end < result.total,
            )
        response = RagResponse(
            status="ANSWERED",
            answer=answer,
            confidence="HIGH",
            project_id=self._request.project_id,
            sources=sources,
            missing_information=[],
            evidence_status="SUFFICIENT",
            context_quality="SUFFICIENT",
            context_relevance=1.0,
            context_completeness=1.0,
            coverage="COMPLETE",
            resolved_intent=f"JIRA_{query.operation.value}",
            conversationContextUpdate=context_update,
            resultPage=result_page,
        )
        provider_operation("JIRA", query.operation.value, "complete", result.total, True)
        stage_complete(
            "provider_execute",
            self._request.project_id,
            began,
            input_count=len(result.evidence),
            output_count=result.total,
            reason_code="COMPLETE",
            language=language,
            model_provider="deterministic",
            model_name="jira-aggregate",
            model_profile="retrieval",
            extra={"snapshot_at": result.snapshot_at or "", "filter_count": len(query.filters)},
        )
        return {"provider_response": response}
