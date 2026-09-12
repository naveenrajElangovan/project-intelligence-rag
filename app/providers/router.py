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
_JIRA_EXPLICIT = re.compile(r"\b(?:jira|issues?|incidencias?|sprints?|backlog)\b", re.I)
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
_ISSUE_KEY = re.compile(r"\b[A-Z][A-Z0-9_]*-\d+\b", re.I)
_REPORT = re.compile(
    r"\b(?:status report|project report|jira report|summary report|"
    r"reporte de estado|informe de estado|reporte del proyecto|informe de jira)\b",
    re.I,
)
_OVERVIEW = re.compile(
    r"\b(?:jira overview|overview of jira|summari[sz]e jira|summari[sz]e (?:the )?(?:whole|entire) jira|"
    r"whole jira|entire jira|complete jira report|resumen (?:general )?de jira|"
    r"resume (?:todo )?jira|informe completo de jira|"
    r"summari[sz]e (?:the )?(?:jira )?project status|project status (?:summary|overview)|"
    r"(?:give|show) me (?:the )?project status|overall project status|how is the project doing|"
    r"resumen del estado del proyecto|resume (?:el )?estado del proyecto|"
    r"muestra (?:el )?estado del proyecto|c[oó]mo va el proyecto)\b",
    re.I,
)
_DETAIL = re.compile(
    r"\b(?:detail|details|detailed|information|summary|status|priority|assignee|assigned|owner|reporter|about|"
    r"due date|created|updated|detalle|detalles|informaci[oó]n|resumen|estado|"
    r"prioridad|asignad[oa]|responsable|reportad[oa]|fecha l[ií]mite|cread[oa]|actualizad[oa]|de qu[eé] trata)\b",
    re.I,
)
_CHILDREN = re.compile(
    r"\b(?:child work items?|child issues?|children|subtasks?|"
    r"elementos? de trabajo secundarios?|issues? hijos?|hijos?|subtareas?)\b",
    re.I,
)
_PENDING_WORK = re.compile(
    r"\b(?:anything pending|pending (?:work|implementation)|remaining work|left to implement|"
    r"outstanding work|hay algo pendiente|trabajo pendiente|falta por implementar|qu[eé] falta)\b",
    re.I,
)
_COMPLETION_CHECK = re.compile(
    r"\b(?:is|was)\s+(?:it|this|that|the\s+(?:ticket|issue|work\s+item))\s+"
    r"(?:done|complete|completed|closed|resolved)\b|"
    r"\b(?:est[aá]|qued[oó])\s+(?:completad[oa]|terminad[oa]|cerrad[oa]|resuelt[oa])\b|"
    r"\b(?:ya\s+)?(?:se\s+)?(?:complet[oó]|termin[oó]|cerr[oó]|resolvi[oó])\b",
    re.I,
)
_TOPIC_STOP_WORDS = {
    "all", "and", "anything", "are", "do", "does", "for", "from", "have", "has", "in",
    "implement", "implementation", "is", "issue", "issues", "jira", "left", "of", "outstanding",
    "pending", "remaining", "the", "ticket", "tickets", "to", "what", "which", "work",
    "algo", "de", "del", "el", "en", "esta", "estan", "falta", "hay", "implementar", "jira",
    "la", "las", "los", "para", "pendiente", "pendientes", "por", "que", "qué", "se", "trabajo",
}
_SECTION_PATTERNS = (
    ("COMMENT", re.compile(r"\b(?:comments?|commented|comentarios?|coment[oó])\b", re.I)),
    (
        "CHANGELOG",
        re.compile(
            r"\b(?:history|changelog|changes?|changed|historial|cambios?|cambi[oó])\b", re.I
        ),
    ),
    ("WORKLOG", re.compile(r"\b(?:worklogs?|work logs?|registros? de trabajo)\b", re.I)),
    (
        "ATTACHMENT",
        re.compile(r"\b(?:attachments?|attached files?|adjuntos?|archivos? adjuntos?)\b", re.I),
    ),
    (
        "RELATIONSHIP",
        re.compile(
            r"\b(?:dependencies|dependency|related issues?|parent|subtasks?|blocks?|blocked by|dependencias?|relacionad[oa]s?|padre|subtareas?|bloquea)\b",
            re.I,
        ),
    ),
    ("ACCEPTANCE", re.compile(r"\b(?:acceptance criteria|criterios? de aceptaci[oó]n)\b", re.I)),
    ("REQUIREMENTS", re.compile(r"\b(?:requirements?|requisitos?)\b", re.I)),
    ("DESCRIPTION", re.compile(r"\b(?:description|descripci[oó]n)\b", re.I)),
    ("CUSTOM_FIELD", re.compile(r"\b(?:custom fields?|campos? personalizados?)\b", re.I)),
    (
        "REMOTE_LINK",
        re.compile(
            r"\b(?:remote links?|external links?|enlaces? remotos?|enlaces? externos?)\b", re.I
        ),
    ),
)


def select_providers(
    question: str,
    enabled: tuple[ProviderName, ...],
    structured_scope: StructuredConversationScope | None = None,
) -> ProviderSelection:
    requested_list = [
        provider
        for provider, pattern in (
            (ProviderName.JIRA, _JIRA_EXPLICIT),
            (ProviderName.GITHUB, _GITHUB),
            (ProviderName.CONFLUENCE, _CONFLUENCE),
        )
        if pattern.search(question)
    ]
    if _ISSUE_KEY.search(question) and ProviderName.JIRA not in requested_list:
        requested_list.insert(0, ProviderName.JIRA)
    requested = tuple(requested_list)
    disabled = tuple(provider for provider in requested if provider not in enabled)
    if disabled:
        return ProviderSelection(
            mode=ExecutionMode.UNAVAILABLE,
            providers=disabled,
            available_providers=enabled,
            reason="REQUESTED_PROVIDER_DISABLED",
        )
    named = requested
    structured = (
        _jira_structured_query(question, assume_jira=len(enabled) == 1)
        if ProviderName.JIRA in enabled
        else None
    )
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


def _jira_structured_query(question: str, *, assume_jira: bool = False) -> StructuredQuery | None:
    keys = tuple(dict.fromkeys(value.upper() for value in _ISSUE_KEY.findall(question)))
    if not (_JIRA.search(question) or assume_jira or keys):
        return None
    if keys and (_GITHUB.search(question) or _CONFLUENCE.search(question)):
        return None
    # A project overview may explicitly request hierarchy, comments, or
    # attachment totals. Those nouns describe requested breakdowns; without a
    # specific issue key they must not narrow the whole request to one section.
    if not keys and _OVERVIEW.search(question):
        return StructuredQuery(
            operation=StructuredOperation.OVERVIEW,
            provider=ProviderName.JIRA,
            filters=_jira_filters(question),
        )
    section_kinds = tuple(
        kind for kind, pattern in _SECTION_PATTERNS if pattern.search(question)
    )
    section_kind = section_kinds[0] if len(section_kinds) == 1 else None
    if keys and _CHILDREN.search(question):
        return StructuredQuery(
            operation=StructuredOperation.DETAIL,
            provider=ProviderName.JIRA,
            filters={"issue_key": keys},
        )
    if section_kinds and (keys or assume_jira or _JIRA_EXPLICIT.search(question)):
        section_filters: dict[str, tuple[str, ...]] = {"section_kind": section_kinds}
        if keys:
            section_filters["issue_key"] = keys
        return StructuredQuery(
            operation=(
                StructuredOperation.SECTION_COUNT
                if _COUNT.search(question)
                else StructuredOperation.SECTION
            ),
            provider=ProviderName.JIRA,
            filters=section_filters,
            section_kind=section_kind,
            section_kinds=section_kinds,
            limit=20,
        )
    if keys and not _CROSS.search(question):
        return StructuredQuery(
            operation=StructuredOperation.DETAIL,
            provider=ProviderName.JIRA,
            filters={"issue_key": keys},
            requested_fact="COMPLETION" if _COMPLETION_CHECK.search(question) else None,
        )
    filters = _jira_filters(question)
    pending_work = bool(_PENDING_WORK.search(question))
    if pending_work:
        filters["status_category_key"] = ("new", "indeterminate")
        topic = _topic_terms(question)
        if topic:
            filters["topic"] = topic
    operation = (
        StructuredOperation.OVERVIEW
        if _OVERVIEW.search(question)
        else StructuredOperation.DISTRIBUTION
        if _DISTRIBUTION.search(question) or _REPORT.search(question)
        else StructuredOperation.COUNT
        if _COUNT.search(question)
        else StructuredOperation.LIST
        if pending_work
        else StructuredOperation.LIST
        if _LIST.search(question)
        and (re.search(r"\b(?:all|todos?|todas?)\b", question, re.I) or bool(filters))
        else None
    )
    if operation is None:
        return None
    if keys:
        filters["issue_key"] = keys
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


def _topic_terms(question: str) -> tuple[str, ...]:
    words = re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9_-]*", question.casefold())
    return tuple(
        dict.fromkeys(word for word in words if len(word) >= 3 and word not in _TOPIC_STOP_WORDS)
    )[:5]


def _jira_filters(question: str) -> dict[str, tuple[str, ...]]:
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
    status_category = next(
        (
            value
            for value, pattern in (
                ("indeterminate", r"\b(?:active|en curso|activ[oa]s?)\b"),
                (
                    "done",
                    r"\b(?:done|closed|completed|terminad[oa]s?|cerrad[oa]s?|completad[oa]s?)\b",
                ),
                ("new", r"\b(?:to do|pending|open|por hacer|pendientes?|abiert[oa]s?)\b"),
            )
            if re.search(pattern, question, re.I)
        ),
        None,
    )
    if status_category and "fixed" not in filters:
        filters["status_category_key"] = (status_category,)
    exact_statuses = {
        "In Progress": r"\b(?:in progress|en progreso)\b",
        "In Review": r"\b(?:in review|review|en revisi[oó]n)\b",
        "Blocked": r"\b(?:blocked|bloquead[oa]s?)\b",
        "QA": r"\b(?:qa|quality assurance|control de calidad)\b",
    }
    matched_statuses = tuple(
        value for value, pattern in exact_statuses.items() if re.search(pattern, question, re.I)
    )
    if matched_statuses:
        filters.pop("status_category_key", None)
        filters["status"] = matched_statuses
    issue_types = {
        "Story": r"\b(?:stories|story|historias?)\b",
        "Task": r"\b(?:tasks?|tareas?)\b",
        "Bug": r"\b(?:bugs?|defects?|errores?|defectos?)\b",
        "Epic": r"\b(?:epics?|[eé]picas?)\b",
    }
    matched_types = tuple(
        value for value, pattern in issue_types.items() if re.search(pattern, question, re.I)
    )
    if matched_types:
        filters["issue_type"] = matched_types
    priorities = {
        "Highest": r"\b(?:highest|m[aá]xima)\b",
        "High": r"\b(?:high priority|priority high|prioridad alta)\b",
        "Medium": r"\b(?:medium priority|priority medium|prioridad media)\b",
        "Low": r"\b(?:low priority|priority low|prioridad baja)\b",
        "Lowest": r"\b(?:lowest|m[ií]nima)\b",
    }
    matched_priorities = tuple(
        value for value, pattern in priorities.items() if re.search(pattern, question, re.I)
    )
    if matched_priorities:
        filters["priority"] = matched_priorities
    return filters


def _jira_structured_followup(
    question: str, scope: StructuredConversationScope
) -> StructuredQuery | None:
    """Resolve typed Jira continuations without using chat text as evidence."""

    filters = {key: tuple(values) for key, values in scope.filters.items()}
    operation = StructuredOperation(scope.operation)
    group_by = scope.group_by
    section_kind = None
    section_kinds: tuple[str, ...] = ()
    requested_fact = None
    offset = 0
    labels = tuple(
        dict.fromkeys(
            value for value in _LABEL_TOKEN.findall(question) if value not in _RESERVED_LABEL_TOKENS
        )
    )
    if _MORE.fullmatch(question):
        operation = (
            StructuredOperation.LIST
            if scope.operation in {"COUNT", "LIST", "DISTRIBUTION"}
            else StructuredOperation.SECTION
            if scope.operation == "SECTION_COUNT"
            else StructuredOperation(scope.operation)
        )
        offset = scope.next_offset
        section_kind = filters.get("section_kind", (None,))[0]
        section_kinds = tuple(filters.get("section_kind", ()))
    elif _COMPLETION_CHECK.search(question):
        issue_keys = filters.get("issue_key", ())
        if len(issue_keys) != 1:
            return None
        filters = {"issue_key": issue_keys}
        operation = StructuredOperation.DETAIL
        requested_fact = "COMPLETION"
    elif candidate := _jira_structured_query(question, assume_jira=True):
        operation = candidate.operation
        group_by = candidate.group_by
        section_kind = candidate.section_kind
        section_kinds = candidate.section_kinds
        incoming = candidate.filters
        if "issue_key" in incoming:
            filters = dict(incoming)
        else:
            if any(
                key in incoming
                for key in (
                    "status",
                    "status_category",
                    "status_category_key",
                    "resolution",
                    "resolution_id",
                    "fixed",
                )
            ):
                for key in (
                    "status",
                    "status_category",
                    "status_category_key",
                    "resolution",
                    "resolution_id",
                    "fixed",
                ):
                    filters.pop(key, None)
            filters.update(incoming)
    elif labels and re.search(
        r"\b(?:what about|and|instead|y|qu[eé] (?:hay )?de)\b", question, re.I
    ):
        filters["labels"] = labels
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
        section_kind=section_kind,
        section_kinds=section_kinds,
        requested_fact=requested_fact,
        offset=offset,
        limit=scope.page_size,
    )
