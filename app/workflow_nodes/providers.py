from __future__ import annotations

import asyncio

from app.models import RagResponse, SourceReference
from app.providers.contracts import ExecutionMode, ProviderName, StructuredOperation
from app.providers.registry import ProviderRegistry
from app.providers.router import select_providers
from app.telemetry import provider_operation, stage_complete, started
from app.workflow_nodes.state import RagState
from app.workflow_support.query_analysis import resolve_response_language


def _language(question: str) -> str:
    return resolve_response_language(question, default="en")


def _filter_text(filters: dict[str, tuple[str, ...]], language: str) -> str:
    values = [value for group in filters.values() for value in group]
    if not values:
        return ""
    joined = ", ".join(values)
    return f" matching {joined}" if language == "en" else f" que coinciden con {joined}"


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
        enabled = tuple(
            ProviderName(value) for value in configured
        ) if self._settings.provider_router_enabled else ()
        selection = select_providers(self._request.question, enabled)
        if selection.mode == ExecutionMode.STRUCTURED and not self._settings.structured_jira_enabled:
            selection = selection.model_copy(update={
                "mode": ExecutionMode.LEGACY,
                "reason": "STRUCTURED_JIRA_DISABLED",
                "structured_query": None,
            })
        if selection.mode == ExecutionMode.FEDERATED and not self._settings.provider_federation_enabled:
            selection = selection.model_copy(update={
                "mode": ExecutionMode.LEGACY,
                "reason": "FEDERATION_DISABLED",
            })
        stage_complete(
            "provider_plan", self._request.project_id, began,
            input_count=1, output_count=len(selection.providers),
            reason_code=selection.reason, language=_language(self._request.question),
            model_provider="deterministic", model_name="provider-router",
            model_profile="retrieval",
            extra={"execution_mode": selection.mode.value, "providers": ",".join(selection.providers)},
        )
        return {"provider_selection": selection}

    def _route_after_provider_plan(self, state: RagState) -> str:
        selection = state.get("provider_selection")
        if selection and selection.mode == ExecutionMode.STRUCTURED:
            return "structured"
        if selection and selection.mode == ExecutionMode.UNAVAILABLE:
            return "unavailable"
        return "legacy"

    async def _provider_unavailable(self, state: RagState) -> RagState:
        selection = state["provider_selection"]
        language = _language(self._request.question)
        names = ", ".join(provider.value for provider in selection.providers)
        response = RagResponse(
            status="INSUFFICIENT_EVIDENCE",
            answer=(
                f"The requested provider ({names}) is disabled for this project."
                if language == "en" else
                f"El proveedor solicitado ({names}) está deshabilitado para este proyecto."
            ),
            confidence="NONE", project_id=self._request.project_id,
            sources=[], missing_information=[f"enabled provider: {names}"],
            evidence_status="INSUFFICIENT", context_quality="INSUFFICIENT",
            coverage="NOT_APPLICABLE", failure_reason="PROVIDER_DISABLED",
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
                    if language == "es" else
                    "No complete authorized Jira snapshot is available for an exact result."
                ),
                confidence="NONE", project_id=self._request.project_id,
                sources=[], missing_information=["complete authorized Jira snapshot"],
                evidence_status="INSUFFICIENT", context_quality="INSUFFICIENT",
                coverage="PARTIAL", failure_reason=reason,
                resolved_intent="JIRA_STRUCTURED_QUERY",
            )
            provider_operation("JIRA", query.operation.value, "incomplete", 0, False)
            stage_complete(
                "provider_execute", self._request.project_id, began,
                reason_code=reason, language=language,
                model_provider="deterministic", model_name="jira-aggregate",
                model_profile="retrieval",
            )
            return {"provider_response": response}
        filter_text = _filter_text(query.filters, language)
        snapshot = f" Snapshot: {result.snapshot_at}." if result.snapshot_at else ""
        if query.operation == StructuredOperation.COUNT:
            answer = (
                f"Jira has {result.total} tickets{filter_text} in {self._request.project_id}.{snapshot}"
                if language == "en" else
                f"Jira tiene {result.total} tickets{filter_text} en {self._request.project_id}.{snapshot}"
            )
        elif query.operation == StructuredOperation.DISTRIBUTION:
            buckets = ", ".join(f"{key}: {value}" for key, value in result.groups.items()) or "none"
            answer = (
                f"Jira has {result.total} tickets{filter_text} in {self._request.project_id}. Breakdown by {query.group_by}: {buckets}.{snapshot}"
                if language == "en" else
                f"Jira tiene {result.total} tickets{filter_text} en {self._request.project_id}. Desglose por {query.group_by}: {buckets}.{snapshot}"
            )
        else:
            rows = result.rows[: self._settings.provider_max_list_items]
            rendered = "; ".join(
                f"{row['key']} — {row['summary']} [{row['status']}]" for row in rows
            )
            answer = (
                f"Jira has {result.total} matching tickets in {self._request.project_id}: {rendered}.{snapshot}"
                if language == "en" else
                f"Jira tiene {result.total} tickets coincidentes en {self._request.project_id}: {rendered}.{snapshot}"
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
        response = RagResponse(
            status="ANSWERED", answer=answer, confidence="HIGH",
            project_id=self._request.project_id, sources=sources,
            missing_information=[], evidence_status="SUFFICIENT",
            context_quality="SUFFICIENT", context_relevance=1.0,
            context_completeness=1.0, coverage="COMPLETE",
            resolved_intent=f"JIRA_{query.operation.value}",
        )
        provider_operation("JIRA", query.operation.value, "complete", result.total, True)
        stage_complete(
            "provider_execute", self._request.project_id, began,
            input_count=len(result.evidence), output_count=result.total,
            reason_code="COMPLETE", language=language,
            model_provider="deterministic", model_name="jira-aggregate",
            model_profile="retrieval",
            extra={"snapshot_at": result.snapshot_at or "", "filter_count": len(query.filters)},
        )
        return {"provider_response": response}
