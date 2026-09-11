from __future__ import annotations

import re

from app.models import StructuredConversationScope
from app.providers.contracts import (
    ExecutionMode,
    ProviderName,
    ProviderSelection,
    StructuredOperation,
    StructuredQuery,
)


_JIRA = re.compile(r"\b(?:jira|tickets?|issues?|incidencias?|historias?)\b", re.I)
_GITHUB = re.compile(
    r"\b(?:github|pull requests?|prs?|commits?|repositor(?:y|ies)|c[oó]digo)\b", re.I
)
_CONFLUENCE = re.compile(
    r"\b(?:confluence|pages?|documentation|docs?|p[aá]ginas?|documentaci[oó]n)\b", re.I
)
_COUNT = re.compile(
    r"\b(?:how many|number of|count|total|cu[aá]nt[oa]s?|n[uú]mero de|total de)\b", re.I
)
_LIST = re.compile(r"\b(?:list|show|which|what are|lista|listar|muestra|cu[aá]les)\b", re.I)
_DISTRIBUTION = re.compile(
    r"\b(?:breakdown|distribution|group(?:ed)? by|desglose|distribuci[oó]n|agrupad[oa]s? por)\b",
    re.I,
)
_CROSS = re.compile(
    r"\b(?:implemented|implementation|pull request|commit|code|documented|documentation|"
    r"implementad[oa]|implementaci[oó]n|c[oó]digo|documentad[oa]|dependenc(?:y|ies)|dependencias?)\b",
    re.I,
)
_LABEL_TOKEN = re.compile(r"\b[A-Z][A-Z_]{1,19}\b")
_RESERVED_LABEL_TOKENS = {"JIRA", "ALL", "THE", "AND", "FOR"}
_MORE = re.compile(
    r"^\s*(?:show\s+more|next|more|continue|muestra\s+m[aá]s|siguiente|contin[uú]a)\s*[?.!]*\s*$",
    re.I,
)
_FIXED = re.compile(r"\b(?:fixed|resolved|corregid[oa]s?|resuelt[oa]s?)\b", re.I)


def select_providers(
    question: str,
    enabled: tuple[ProviderName, ...],
    structured_scope: StructuredConversationScope | None = None,
) -> ProviderSelection:
    requested = tuple(
        provider
        for provider, pattern in (
            (ProviderName.JIRA, _JIRA),
            (ProviderName.GITHUB, _GITHUB),
            (ProviderName.CONFLUENCE, _CONFLUENCE),
        )
        if pattern.search(question)
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
    inherited = False
    if (
        structured is None
        and structured_scope is not None
        and structured_scope.provider == ProviderName.JIRA.value
        and not requested
        and ProviderName.JIRA in enabled
    ):
        structured = _jira_structured_followup(question, structured_scope)
        inherited = structured is not None
    if structured is not None:
        return ProviderSelection(
            mode=ExecutionMode.STRUCTURED,
            providers=(ProviderName.JIRA,),
            reason=(
                "JIRA_STRUCTURED_CONTEXT_INHERITED" if inherited else "JIRA_COMPLETE_AGGREGATE"
            ),
            structured_query=structured,
            available_providers=enabled,
        )
    if len(named) > 1 or (ProviderName.JIRA in named and _CROSS.search(question)):
        providers = named
        if len(providers) == 1:
            providers = tuple(
                provider
                for provider in enabled
                if provider in {ProviderName.JIRA, ProviderName.GITHUB, ProviderName.CONFLUENCE}
            )
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
    if structured_scope is None and (
        _MORE.fullmatch(question) or (_FIXED.search(question) and _LIST.search(question))
    ):
        return ProviderSelection(
            mode=ExecutionMode.CLARIFICATION,
            providers=(ProviderName.JIRA,),
            available_providers=enabled,
            reason="STRUCTURED_CONTEXT_REQUIRED",
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
        StructuredOperation.DISTRIBUTION
        if _DISTRIBUTION.search(question)
        else StructuredOperation.COUNT
        if _COUNT.search(question)
        else StructuredOperation.LIST
        if _LIST.search(question) and re.search(r"\b(?:all|todos?|todas?)\b", question, re.I)
        else None
    )
    if operation is None:
        return None
    filters: dict[str, tuple[str, ...]] = {}
    labels = tuple(
        dict.fromkeys(
            value for value in _LABEL_TOKEN.findall(question) if value not in _RESERVED_LABEL_TOKENS
        )
    )
    if labels:
        filters["labels"] = labels
    if _FIXED.search(question):
        filters["fixed"] = ("AUTO",)
    for field, values in {
        "status": ("To Do", "In Progress", "In Review", "Done"),
        "issue_type": ("Story", "Task", "Bug", "Epic"),
        "priority": ("Highest", "High", "Medium", "Low", "Lowest"),
    }.items():
        matched = tuple(
            value for value in values if re.search(rf"\b{re.escape(value)}\b", question, re.I)
        )
        if matched:
            filters[field] = matched
    group_by = None
    if operation == StructuredOperation.DISTRIBUTION:
        group_by = (
            "issue_type"
            if re.search(r"\b(?:type|tipo)\b", question, re.I)
            else "priority"
            if re.search(r"\b(?:priority|prioridad)\b", question, re.I)
            else "status"
        )
    return StructuredQuery(
        operation=operation,
        provider=ProviderName.JIRA,
        filters=filters,
        group_by=group_by,
    )


def _jira_structured_followup(
    question: str, scope: StructuredConversationScope
) -> StructuredQuery | None:
    """Resolve typed Jira continuations without using chat text as evidence."""

    filters = {key: tuple(values) for key, values in scope.filters.items()}
    operation = StructuredOperation(scope.operation)
    group_by = scope.group_by
    offset = 0
    labels = tuple(
        dict.fromkeys(
            value for value in _LABEL_TOKEN.findall(question) if value not in _RESERVED_LABEL_TOKENS
        )
    )
    if _MORE.fullmatch(question):
        operation = StructuredOperation.LIST
        offset = scope.next_offset
    elif _FIXED.search(question):
        operation = StructuredOperation.LIST if _LIST.search(question) else operation
        for key in (
            "status",
            "status_category",
            "status_category_key",
            "resolution",
            "resolution_id",
        ):
            filters.pop(key, None)
        filters["fixed"] = ("AUTO",)
    elif labels and re.search(
        r"\b(?:what about|and|instead|y|qu[eé] (?:hay )?de)\b", question, re.I
    ):
        filters["labels"] = labels
    elif (
        _COUNT.search(question)
        or _DISTRIBUTION.search(question)
        or (_LIST.search(question) and re.search(r"\b(?:all|todos?|todas?)\b", question, re.I))
    ):
        operation = (
            StructuredOperation.DISTRIBUTION
            if _DISTRIBUTION.search(question)
            else StructuredOperation.COUNT
            if _COUNT.search(question)
            else StructuredOperation.LIST
        )
        if labels:
            filters["labels"] = labels
        for field, values in {
            "status": ("To Do", "In Progress", "In Review", "Done"),
            "issue_type": ("Story", "Task", "Bug", "Epic"),
            "priority": ("Highest", "High", "Medium", "Low", "Lowest"),
        }.items():
            matched = tuple(
                value for value in values if re.search(rf"\b{re.escape(value)}\b", question, re.I)
            )
            if matched:
                if field == "status":
                    filters.pop("fixed", None)
                    for key in (
                        "status_category",
                        "status_category_key",
                        "resolution",
                        "resolution_id",
                    ):
                        filters.pop(key, None)
                filters[field] = matched
    else:
        return None
    if operation == StructuredOperation.DISTRIBUTION:
        group_by = (
            "issue_type"
            if re.search(r"\b(?:type|tipo)\b", question, re.I)
            else "priority"
            if re.search(r"\b(?:priority|prioridad)\b", question, re.I)
            else "status"
        )
    return StructuredQuery(
        operation=operation,
        provider=ProviderName.JIRA,
        filters=filters,
        group_by=group_by,
        offset=offset,
        limit=scope.page_size,
    )
