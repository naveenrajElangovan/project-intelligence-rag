from __future__ import annotations

import json

from langchain_core.documents import Document

from app.providers.contracts import (
    EvidenceEnvelope,
    ProviderAdapter,
    ProviderCapabilities,
    ProviderName,
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
                operation=query.operation, provider=self.name, complete=False,
                degradation=("AGGREGATE_UNSUPPORTED",),
            )
        loader = getattr(self._retriever, "authorized_source_snapshot", None)
        if loader is None:
            return StructuredResult(
                operation=query.operation, provider=self.name, complete=False,
                degradation=("COMPLETE_SNAPSHOT_UNAVAILABLE",),
            )
        documents, complete = await loader(("ISSUE",))
        current = [
            document for document in documents
            # ISSUE is the established Jira source contract. Older Jira
            # snapshots predate the redundant provider metadata, so requiring
            # provider=JIRA would silently turn a complete legacy snapshot into
            # an exact zero result.
            if str(document.metadata.get("source_type") or "").upper() == "ISSUE"
            and str(document.metadata.get("jira_chunk_kind") or "") == "CURRENT"
        ]
        matched = [document for document in current if _matches(document, query.filters)]
        unique: dict[str, Document] = {}
        for document in matched:
            key = str(document.metadata.get("cloud_id") or "") + ":" + _identity(document)
            if key != ":":
                unique[key] = document
        ordered = sorted(unique.values(), key=lambda item: str(item.metadata.get("issue_key") or ""))
        groups: dict[str, int] = {}
        if query.group_by:
            for document in ordered:
                value = str(document.metadata.get(query.group_by) or "Unspecified")
                groups[value] = groups.get(value, 0) + 1
        snapshot_at = max(
            (str(document.metadata.get("issue_updated") or "") for document in current),
            default="",
        ) or None
        return StructuredResult(
            operation=query.operation,
            provider=self.name,
            complete=complete,
            snapshot_at=snapshot_at,
            total=len(ordered),
            rows=tuple(_row(document) for document in ordered),
            groups=dict(sorted(groups.items())),
            evidence=tuple(_envelope(self.name, self._project_id, document) for document in ordered),
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
        return max(
            (str(item.metadata.get("issue_updated") or item.metadata.get("event_date") or "") for item in documents),
            default="",
        ) or None


def _matches(document: Document, filters: dict[str, tuple[str, ...]]) -> bool:
    metadata = document.metadata
    for field, expected in filters.items():
        actual = _values(metadata.get(field))
        if not actual:
            scalar = str(metadata.get(field) or "").strip()
            actual = (scalar,) if scalar else ()
        folded = {value.casefold() for value in actual}
        if not any(value.casefold() in folded for value in expected):
            return False
    return True


def _row(document: Document) -> dict[str, object]:
    metadata = document.metadata
    return {
        "key": str(metadata.get("issue_key") or ""),
        "summary": str(metadata.get("title") or ""),
        "status": str(metadata.get("status") or ""),
        "issue_type": str(metadata.get("issue_type") or ""),
        "priority": str(metadata.get("priority") or ""),
        "labels": _values(metadata.get("labels")),
        "url": str(metadata.get("source_url") or ""),
    }
