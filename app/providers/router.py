from __future__ import annotations

import re

from app.providers.contracts import (
    ExecutionMode,
    ProviderName,
    ProviderSelection,
    StructuredOperation,
    StructuredQuery,
)


_JIRA = re.compile(r"\b(?:jira|tickets?|issues?|incidencias?|historias?)\b", re.I)
_GITHUB = re.compile(r"\b(?:github|pull requests?|prs?|commits?|repositor(?:y|ies)|c[oó]digo)\b", re.I)
_CONFLUENCE = re.compile(r"\b(?:confluence|pages?|documentation|docs?|p[aá]ginas?|documentaci[oó]n)\b", re.I)
_COUNT = re.compile(r"\b(?:how many|number of|count|total|cu[aá]nt[oa]s?|n[uú]mero de|total de)\b", re.I)
_LIST = re.compile(r"\b(?:list|show|which|what are|lista|listar|muestra|cu[aá]les)\b", re.I)
_DISTRIBUTION = re.compile(r"\b(?:breakdown|distribution|group(?:ed)? by|desglose|distribuci[oó]n|agrupad[oa]s? por)\b", re.I)
_CROSS = re.compile(
    r"\b(?:implemented|implementation|pull request|commit|code|documented|documentation|"
    r"implementad[oa]|implementaci[oó]n|c[oó]digo|documentad[oa]|dependenc(?:y|ies)|dependencias?)\b",
    re.I,
)
_LABEL_TOKEN = re.compile(r"\b[A-Z][A-Z_]{1,19}\b")
_RESERVED_LABEL_TOKENS = {"JIRA", "ALL", "THE", "AND", "FOR"}


def select_providers(question: str, enabled: tuple[ProviderName, ...]) -> ProviderSelection:
    requested = tuple(
        provider for provider, pattern in (
            (ProviderName.JIRA, _JIRA),
            (ProviderName.GITHUB, _GITHUB),
            (ProviderName.CONFLUENCE, _CONFLUENCE),
        ) if pattern.search(question)
    )
    disabled = tuple(provider for provider in requested if provider not in enabled)
    if disabled:
        return ProviderSelection(
            mode=ExecutionMode.UNAVAILABLE,
            providers=disabled,
            available_providers=enabled,
            reason="REQUESTED_PROVIDER_DISABLED",
        )
    named = requested
    structured = _jira_structured_query(question) if ProviderName.JIRA in enabled else None
    if structured is not None:
        return ProviderSelection(
            mode=ExecutionMode.STRUCTURED,
            providers=(ProviderName.JIRA,),
            reason="JIRA_COMPLETE_AGGREGATE",
            structured_query=structured,
            available_providers=enabled,
        )
    if len(named) > 1 or (ProviderName.JIRA in named and _CROSS.search(question)):
        providers = named
        if len(providers) == 1:
            providers = tuple(provider for provider in enabled if provider in {
                ProviderName.JIRA, ProviderName.GITHUB, ProviderName.CONFLUENCE
            })
        return ProviderSelection(
            mode=ExecutionMode.FEDERATED,
            providers=providers,
            reason="CROSS_PROVIDER_EVIDENCE_REQUIRED",
            available_providers=enabled,
        )
    if len(named) == 1:
        return ProviderSelection(
            mode=ExecutionMode.SINGLE_PROVIDER,
            providers=named,
            available_providers=enabled,
            reason="EXPLICIT_PROVIDER",
        )
    # Preserve the byte-for-byte legacy planning and retrieval path for ordinary
    # single-provider and unscoped questions during the compatibility rollout.
    return ProviderSelection(
        mode=ExecutionMode.LEGACY,
        providers=named,
        reason="LEGACY_PASSTHROUGH",
        available_providers=enabled,
    )


def _jira_structured_query(question: str) -> StructuredQuery | None:
    if not _JIRA.search(question):
        return None
    operation = (
        StructuredOperation.DISTRIBUTION if _DISTRIBUTION.search(question)
        else StructuredOperation.COUNT if _COUNT.search(question)
        else StructuredOperation.LIST if _LIST.search(question) and re.search(r"\b(?:all|todos?|todas?)\b", question, re.I)
        else None
    )
    if operation is None:
        return None
    filters: dict[str, tuple[str, ...]] = {}
    labels = tuple(
        dict.fromkeys(
            value for value in _LABEL_TOKEN.findall(question)
            if value not in _RESERVED_LABEL_TOKENS
        )
    )
    if labels:
        filters["labels"] = labels
    for field, values in {
        "status": ("To Do", "In Progress", "In Review", "Done"),
        "issue_type": ("Story", "Task", "Bug", "Epic"),
        "priority": ("Highest", "High", "Medium", "Low", "Lowest"),
    }.items():
        matched = tuple(value for value in values if re.search(rf"\b{re.escape(value)}\b", question, re.I))
        if matched:
            filters[field] = matched
    group_by = None
    if operation == StructuredOperation.DISTRIBUTION:
        group_by = "issue_type" if re.search(r"\b(?:type|tipo)\b", question, re.I) else "priority" if re.search(r"\b(?:priority|prioridad)\b", question, re.I) else "status"
    return StructuredQuery(
        operation=operation,
        provider=ProviderName.JIRA,
        filters=filters,
        group_by=group_by,
    )
