from __future__ import annotations

import json
import re
import unicodedata

from langchain_core.documents import Document

from app.providers.contracts import (
    EvidenceEnvelope,
    ProviderAdapter,
    ProviderCapabilities,
    ProviderName,
    StructuredOperation,
    StructuredQuery,
    StructuredResult,
)


_SOURCE_TYPES = {
    ProviderName.JIRA: ("ISSUE", "ATTACHMENT"),
    ProviderName.GITHUB: ("CODE",),
    ProviderName.CONFLUENCE: ("PAGE", "ATTACHMENT"),
}


def _values(value: object) -> tuple[str, ...]:
    if isinstance(value, (list, tuple, set)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ()
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            if isinstance(parsed, list):
                return tuple(str(item).strip() for item in parsed if str(item).strip())
        return tuple(item.strip() for item in text.split(",") if item.strip())
    return ()


def _identity(document: Document) -> str:
    metadata = document.metadata
    return str(
        metadata.get("source_id")
        or metadata.get("entity_key")
        or metadata.get("issue_key")
        or metadata.get("chunk_id")
        or ""
    )


def _envelope(provider: ProviderName, project_id: str, document: Document) -> EvidenceEnvelope:
    metadata = document.metadata
    return EvidenceEnvelope(
        provider=provider,
        project_id=project_id,
        source_type=str(metadata.get("source_type") or "DOCUMENT"),
        source_id=_identity(document),
        source_url=str(metadata.get("source_url") or "") or None,
        locator=str(metadata.get("locator") or "") or None,
        access_policy_id=str(metadata.get("access_policy_id") or ""),
        source_version=str(metadata.get("source_version") or metadata.get("issue_updated") or ""),
        event_date=str(metadata.get("event_date") or metadata.get("issue_updated") or "") or None,
        current=str(metadata.get("jira_chunk_kind") or "CURRENT") == "CURRENT",
        authority=provider.value,
        score=float(metadata.get("rerank_score") or metadata.get("score") or 0.0),
        document=document,
    )


class IndexedProviderAdapter(ProviderAdapter):
    def __init__(self, provider: ProviderName, project_id: str, retriever: object) -> None:
        self.name = provider
        self._project_id = project_id
        self._retriever = retriever

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            aggregates=self.name == ProviderName.JIRA,
            history=self.name == ProviderName.JIRA,
            attachments=self.name in {ProviderName.JIRA, ProviderName.CONFLUENCE},
            relationships=self.name in {ProviderName.JIRA, ProviderName.GITHUB},
        )

    async def retrieve(self, query: str) -> tuple[EvidenceEnvelope, ...]:
        loader = getattr(self._retriever, "ainvoke_scoped")
        documents = await loader(query, _SOURCE_TYPES[self.name])
        return tuple(_envelope(self.name, self._project_id, document) for document in documents)

    async def lookup(self, identifiers: tuple[str, ...]) -> tuple[EvidenceEnvelope, ...]:
        loader = getattr(self._retriever, "ainvoke_exact_identifiers")
        documents = await loader(identifiers, _SOURCE_TYPES[self.name])
        return tuple(_envelope(self.name, self._project_id, document) for document in documents)

    async def aggregate(self, query: StructuredQuery) -> StructuredResult:
        if self.name != ProviderName.JIRA:
            return StructuredResult(
                operation=query.operation,
                provider=self.name,
                complete=False,
                degradation=("AGGREGATE_UNSUPPORTED",),
            )
        loader = getattr(self._retriever, "authorized_source_snapshot", None)
        if loader is None:
            return StructuredResult(
                operation=query.operation,
                provider=self.name,
                complete=False,
                degradation=("COMPLETE_SNAPSHOT_UNAVAILABLE",),
            )
        if query.operation in {StructuredOperation.SECTION, StructuredOperation.SECTION_COUNT}:
            return await self._jira_sections(query, loader)
        documents, complete = await loader(("ISSUE",))
        current = [
            document
            for document in documents
            # ISSUE is the established Jira source contract. Older Jira
            # snapshots predate the redundant provider metadata, so requiring
            # provider=JIRA would silently turn a complete legacy snapshot into
            # an exact zero result.
            if str(document.metadata.get("source_type") or "").upper() == "ISSUE"
            and str(document.metadata.get("jira_chunk_kind") or "") == "CURRENT"
        ]
        effective_filters, fixed_rule, clarification_options = _resolve_fixed_filter(
            current, query.filters
        )
        if clarification_options:
            return StructuredResult(
                operation=query.operation,
                provider=self.name,
                complete=True,
                snapshot_at=_snapshot_at(current),
                clarification_options=clarification_options,
                applied_filter_rule="AMBIGUOUS_RESOLUTION",
            )
        matched = [document for document in current if _matches(document, effective_filters)]
        unique: dict[str, Document] = {}
        for document in matched:
            key = str(document.metadata.get("cloud_id") or "") + ":" + _identity(document)
            if key != ":":
                unique[key] = document
        ordered = sorted(unique.values(), key=_jira_sort_key)
        groups: dict[str, int] = {}
        if query.group_by:
            for document in ordered:
                value = str(document.metadata.get(query.group_by) or "Unspecified")
                groups[value] = groups.get(value, 0) + 1
        snapshot_at = _snapshot_at(current)
        page = ordered[query.offset : query.offset + query.limit]
        evidence_documents = page if query.operation.value == "LIST" else ordered
        return StructuredResult(
            operation=query.operation,
            provider=self.name,
            complete=complete,
            snapshot_at=snapshot_at,
            total=len(ordered),
            rows=tuple(_row(document) for document in page),
            groups=dict(sorted(groups.items())),
            evidence=tuple(
                _envelope(self.name, self._project_id, document) for document in evidence_documents
            ),
            degradation=() if complete else ("SNAPSHOT_TRUNCATED",),
            applied_filter_rule=fixed_rule,
        )

    async def _jira_sections(self, query: StructuredQuery, loader: object) -> StructuredResult:
        section_kind = str(
            query.section_kind or next(iter(query.filters.get("section_kind", ())), "")
        ).upper()
        source_types = ("ATTACHMENT",) if section_kind == "ATTACHMENT" else ("ISSUE",)
        documents, complete = await loader(source_types)
        filters = {key: values for key, values in query.filters.items() if key != "section_kind"}
        matched = [
            document
            for document in documents
            if (
                (
                    section_kind == "ATTACHMENT"
                    and str(document.metadata.get("source_type") or "").upper() == "ATTACHMENT"
                )
                or str(document.metadata.get("jira_chunk_kind") or "").upper() == section_kind
            )
            and _matches(document, filters)
        ]
        records: dict[str, list[Document]] = {}
        for document in matched:
            metadata = document.metadata
            identity = ":".join(
                (
                    str(metadata.get("cloud_id") or ""),
                    str(metadata.get("issue_key") or ""),
                    section_kind,
                    str(
                        metadata.get("event_id")
                        or metadata.get("attachment_id")
                        or metadata.get("locator")
                        or metadata.get("source_id")
                        or metadata.get("chunk_id")
                        or ""
                    ),
                )
            )
            records.setdefault(identity, []).append(document)
        ordered = sorted(
            records.values(),
            key=lambda group: (
                str(group[0].metadata.get("issue_key") or ""),
                str(group[0].metadata.get("event_date") or ""),
                str(group[0].metadata.get("event_id") or ""),
            ),
        )
        page = ordered[query.offset : query.offset + query.limit]
        rows = tuple(_section_row(group, section_kind) for group in page)
        evidence_groups = ordered if query.operation == StructuredOperation.SECTION_COUNT else page
        evidence = tuple(
            _envelope(self.name, self._project_id, group[0]) for group in evidence_groups
        )
        return StructuredResult(
            operation=query.operation,
            provider=self.name,
            complete=complete,
            snapshot_at=_snapshot_at(documents),
            total=len(ordered),
            rows=rows,
            evidence=evidence,
            degradation=() if complete else ("SNAPSHOT_TRUNCATED",),
        )

    async def health(self) -> bool:
        try:
            loader = getattr(self._retriever, "authorized_source_snapshot")
            await loader((_SOURCE_TYPES[self.name][0],))
            return True
        except Exception:
            return False

    async def freshness(self) -> str | None:
        loader = getattr(self._retriever, "authorized_source_snapshot")
        documents, _complete = await loader((_SOURCE_TYPES[self.name][0],))
        return (
            max(
                (
                    str(item.metadata.get("issue_updated") or item.metadata.get("event_date") or "")
                    for item in documents
                ),
                default="",
            )
            or None
        )


def _matches(document: Document, filters: dict[str, tuple[str, ...]]) -> bool:
    metadata = document.metadata
    for field, expected in filters.items():
        actual = _values(metadata.get(field))
        if field == "status_category_key" and not actual:
            normalized_status = _normalized(str(metadata.get("status") or ""))
            legacy_category = {
                "to do": "new",
                "open": "new",
                "in progress": "indeterminate",
                "in review": "indeterminate",
                "qa": "indeterminate",
                "done": "done",
                "closed": "done",
                "resolved": "done",
            }.get(normalized_status)
            actual = (legacy_category,) if legacy_category else ()
        if not actual:
            scalar = str(metadata.get(field) or "").strip()
            actual = (scalar,) if scalar else ()
        folded = {value.casefold() for value in actual}
        if not any(value.casefold() in folded for value in expected):
            return False
    return True


def _normalized(value: str) -> str:
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value).casefold()
        if not unicodedata.combining(character)
    )


def _resolve_fixed_filter(
    documents: list[Document], filters: dict[str, tuple[str, ...]]
) -> tuple[dict[str, tuple[str, ...]], str | None, tuple[str, ...]]:
    effective = {key: tuple(value) for key, value in filters.items() if key != "fixed"}
    if "fixed" not in filters:
        return effective, None, ()
    fixed_aliases = {"fixed", "resolved", "corregido", "corregida", "resuelto", "resuelta"}
    observed = sorted(
        {
            str(document.metadata.get("resolution") or "").strip()
            for document in documents
            if str(document.metadata.get("resolution") or "").strip()
        }
    )
    matching = tuple(value for value in observed if _normalized(value) in fixed_aliases)
    if len(matching) > 1:
        return effective, "AMBIGUOUS_RESOLUTION", matching
    if matching:
        effective["resolution"] = matching
        return effective, f"RESOLUTION:{matching[0]}", ()
    if any("status_category_key" in document.metadata for document in documents):
        effective["status_category_key"] = ("done",)
        return effective, "STATUS_CATEGORY:DONE", ()
    # Compatibility for Jira snapshots ingested before status-category metadata.
    effective["status"] = ("Done",)
    return effective, "LEGACY_STATUS:DONE", ()


def _snapshot_at(documents: list[Document]) -> str | None:
    return (
        max(
            (str(document.metadata.get("issue_updated") or "") for document in documents),
            default="",
        )
        or None
    )


def _jira_sort_key(document: Document) -> tuple[str, int, str]:
    key = str(document.metadata.get("issue_key") or "")
    match = re.fullmatch(r"(.+?)-(\d+)", key)
    if match:
        return match.group(1).casefold(), int(match.group(2)), key.casefold()
    return key.casefold(), 0, key.casefold()


def _row(document: Document) -> dict[str, object]:
    metadata = document.metadata
    return {
        "key": str(metadata.get("issue_key") or ""),
        "summary": str(metadata.get("title") or ""),
        "status": str(metadata.get("status") or ""),
        "status_category": str(metadata.get("status_category") or ""),
        "status_category_key": str(metadata.get("status_category_key") or ""),
        "resolution": str(metadata.get("resolution") or ""),
        "resolution_id": str(metadata.get("resolution_id") or ""),
        "issue_type": str(metadata.get("issue_type") or ""),
        "priority": str(metadata.get("priority") or ""),
        "labels": _values(metadata.get("labels")),
        "assignee": str(metadata.get("assignee") or ""),
        "reporter": str(metadata.get("reporter") or ""),
        "due_date": str(metadata.get("due_date") or ""),
        "updated": str(metadata.get("issue_updated") or ""),
        "url": str(metadata.get("source_url") or ""),
    }


def _section_row(documents: list[Document], section_kind: str) -> dict[str, object]:
    ordered = sorted(documents, key=lambda item: int(item.metadata.get("chunk_ordinal") or 0))
    metadata = ordered[0].metadata
    parts = list(
        dict.fromkeys(
            document.page_content.strip() for document in ordered if document.page_content.strip()
        )
    )
    text = "\n".join(parts)
    lines = text.splitlines()
    if lines and lines[0].upper().startswith(section_kind + " "):
        text = "\n".join(lines[1:]).strip()
    if section_kind == "CHANGELOG" and text.startswith("["):
        try:
            changes = json.loads(text)
            text = "\n".join(
                f"{change.get('field', 'Field')}: "
                f"{change.get('fromString') or 'not set'} → {change.get('toString') or 'not set'}"
                for change in changes
                if isinstance(change, dict)
            )
        except (TypeError, ValueError):
            pass
    return {
        "key": str(metadata.get("issue_key") or ""),
        "kind": section_kind,
        "event_id": str(metadata.get("event_id") or metadata.get("attachment_id") or ""),
        "event_date": str(metadata.get("event_date") or metadata.get("attachment_created") or ""),
        "author": str(metadata.get("event_author") or metadata.get("attachment_author") or ""),
        "title": str(metadata.get("title") or metadata.get("file_name") or ""),
        "text": text[:4000],
        "url": str(metadata.get("source_url") or ""),
    }
