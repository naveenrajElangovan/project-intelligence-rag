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
    remaining = {key: values for key, values in filters.items() if key != "fixed"}
    clauses: list[str] = []
    topics = remaining.pop("topic", ())
    if topics:
        joined_topics = ", ".join(f"**{value}**" for value in topics)
        clauses.append(f"sobre {joined_topics}" if language == "es" else f"about {joined_topics}")
    categories = remaining.get("status_category_key", ())
    if set(categories) == {"new", "indeterminate"}:
        remaining.pop("status_category_key")
        clauses.append(
            "que aún no están en la categoría Done de Jira"
            if language == "es"
            else "that are not yet in Jira's Done status category"
        )
    values = [value for group in remaining.values() for value in group]
    if values:
        joined = ", ".join(f"**{value}**" for value in values)
        clauses.append(f"que coinciden con {joined}" if language == "es" else f"matching {joined}")
    if not clauses:
        return ""
    return " " + " ".join(clauses)


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
        if query.operation == StructuredOperation.OVERVIEW:
            overview = result.rows[0] if result.rows else {}

            def breakdown(values: object, *, limit: int | None = None) -> str:
                if not isinstance(values, dict) or not values:
                    return "- None" if language == "en" else "- Ninguno"
                items = list(values.items())
                shown = items[:limit] if limit else items
                lines = [f"- **{key}:** {value}" for key, value in shown]
                if limit and len(items) > limit:
                    remaining = len(items) - limit
                    lines.append(
                        f"- _{remaining} additional values; ask for the complete distribution._"
                        if language == "en"
                        else f"- _{remaining} valores adicionales; solicita la distribución completa._"
                    )
                return "\n".join(lines)

            labels = breakdown(overview.get("labels"), limit=15)
            components = breakdown(overview.get("components"), limit=15)
            answer = (
                (
                    f"## Jira project overview — {self._request.project_id}\n\n"
                    f"- **Total work items:** {result.total}\n"
                    f"- **Top-level work items:** {overview.get('top_level_work_items', 0)}\n"
                    f"- **Child work items:** {overview.get('child_work_items', 0)}\n\n"
                    f"### Statuses\n{breakdown(overview.get('statuses'))}\n\n"
                    f"### Work item types\n{breakdown(overview.get('issue_types'))}\n\n"
                    f"### Priorities\n{breakdown(overview.get('priorities'))}\n\n"
                    f"### Labels\n{labels}\n\n### Components\n{components}{snapshot}"
                )
                if language == "en"
                else (
                    f"## Resumen del proyecto Jira — {self._request.project_id}\n\n"
                    f"- **Total de elementos:** {result.total}\n"
                    f"- **Elementos de nivel superior:** {overview.get('top_level_work_items', 0)}\n"
                    f"- **Elementos hijos:** {overview.get('child_work_items', 0)}\n\n"
                    f"### Estados\n{breakdown(overview.get('statuses'))}\n\n"
                    f"### Tipos de elemento\n{breakdown(overview.get('issue_types'))}\n\n"
                    f"### Prioridades\n{breakdown(overview.get('priorities'))}\n\n"
                    f"### Etiquetas\n{labels}\n\n### Componentes\n{components}{snapshot}"
                )
            )
        elif query.operation == StructuredOperation.COUNT:
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
            parent_rows = [row for row in result.rows if row.get("row_role") != "CHILD"]
            child_rows = [row for row in result.rows if row.get("row_role") == "CHILD"]
            if not parent_rows:
                answer = (
                    f"No matching Jira issue was found in **{self._request.project_id}**.{snapshot}"
                    if language == "en"
                    else f"No se encontró un issue de Jira coincidente en **{self._request.project_id}**.{snapshot}"
                )
            elif query.requested_fact == "COMPLETION":
                row = parent_rows[0]
                category = str(row.get("status_category_key") or "").casefold()
                status = str(row.get("status") or "")
                legacy_done = status.casefold() in {"done", "closed", "resolved"}
                completed = category == "done" or (not category and legacy_done)
                key = str(row.get("key") or "")
                if language == "es":
                    answer = (
                        f"**Sí. {key} está completado.** Su estado actual en Jira es **{status}**."
                        if completed
                        else f"**No. {key} no está completado.** Su estado actual en Jira es **{status}**."
                    ) + snapshot
                else:
                    answer = (
                        f"**Yes. {key} is complete.** Its current Jira status is **{status}**."
                        if completed
                        else f"**No. {key} is not complete.** Its current Jira status is **{status}**."
                    ) + snapshot
            else:
                rendered_details = []
                for row in parent_rows:
                    labels = (
                        ("Estado", "Tipo", "Prioridad", "Responsable", "Reportó", "Fecha límite")
                        if language == "es"
                        else ("Status", "Type", "Priority", "Assignee", "Reporter", "Due date")
                    )
                    fields = [
                        f"**{labels[0]}:** {row['status']}",
                        f"**{labels[1]}:** {row['issue_type']}",
                        f"**{labels[2]}:** {row['priority'] or ('No definida' if language == 'es' else 'Not set')}",
                    ]
                    if row.get("assignee"):
                        fields.append(f"**{labels[3]}:** {row['assignee']}")
                    if row.get("reporter"):
                        fields.append(f"**{labels[4]}:** {row['reporter']}")
                    if row.get("due_date"):
                        fields.append(f"**{labels[5]}:** {row['due_date']}")
                    if row.get("parent_issue_key"):
                        fields.append(
                            f"**{'Padre' if language == 'es' else 'Parent'}:** {row['parent_issue_key']}"
                        )
                    if row.get("labels"):
                        fields.append(
                            f"**{'Etiquetas' if language == 'es' else 'Labels'}:** {', '.join(row['labels'])}"
                        )
                    if row.get("resolution"):
                        fields.append(
                            f"**{'Resolución' if language == 'es' else 'Resolution'}:** {row['resolution']}"
                        )
                    if row.get("updated"):
                        fields.append(
                            f"**{'Actualizado' if language == 'es' else 'Updated'}:** {row['updated']}"
                        )
                    section_counts = row.get("section_counts")
                    if isinstance(section_counts, dict) and section_counts:
                        fields.append(
                            f"**{'Contenido indexado' if language == 'es' else 'Indexed content'}:** "
                            + ", ".join(
                                f"{kind.replace('_', ' ').title()} {count}"
                                for kind, count in section_counts.items()
                            )
                        )
                    if row.get("description"):
                        fields.append(
                            f"**{'Descripción' if language == 'es' else 'Description'}:** {row['description']}"
                        )
                    rendered_details.append(
                        f"### {row['key']} — {row['summary']}\n"
                        + "\n".join(f"- {field}" for field in fields)
                    )
                children_heading = (
                    f"#### Elementos de trabajo hijos ({len(child_rows)})"
                    if language == "es"
                    else f"#### Child work items ({len(child_rows)})"
                )
                children = (
                    "\n".join(
                        f"- **{row['key']}** — {row['summary']} · {row['issue_type']} · {row['status']}"
                        for row in child_rows
                    )
                    if child_rows
                    else ("- Ninguno" if language == "es" else "- None")
                )
                answer = "\n\n".join(rendered_details) + f"\n\n{children_heading}\n{children}" + snapshot
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
                f"- **{row['key']}** — {row['summary']} · {row['issue_type']} · {row['status']}"
                + (f" · {row['priority']}" if row.get("priority") else "")
                + (f" · parent {row['parent_issue_key']}" if row.get("parent_issue_key") else "")
                for row in rows
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
                    f"Found **{result.total} {ticket_noun}**{filter_summary}{rule_text} in **{self._request.project_id}**.\n\n{rendered}\n\n{page_text}{snapshot}"
                    if language == "en"
                    else f"Se encontraron **{result.total} {ticket_noun}**{filter_summary}{rule_text} en **{self._request.project_id}**.\n\n{rendered}\n\n{page_text}{snapshot}"
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
