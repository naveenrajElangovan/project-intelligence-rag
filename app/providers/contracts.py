from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, Field


class ProviderName(StrEnum):
    JIRA = "JIRA"
    GITHUB = "GITHUB"
    CONFLUENCE = "CONFLUENCE"


class ExecutionMode(StrEnum):
    LEGACY = "LEGACY"
    SINGLE_PROVIDER = "SINGLE_PROVIDER"
    FEDERATED = "FEDERATED"
    STRUCTURED = "STRUCTURED"
    UNAVAILABLE = "UNAVAILABLE"
    CLARIFICATION = "CLARIFICATION"


class StructuredOperation(StrEnum):
    COUNT = "COUNT"
    LIST = "LIST"
    DISTRIBUTION = "DISTRIBUTION"
    DETAIL = "DETAIL"
    SECTION = "SECTION"
    SECTION_COUNT = "SECTION_COUNT"


class ProviderCapabilities(BaseModel):
    semantic_search: bool = True
    exact_lookup: bool = True
    aggregates: bool = False
    history: bool = False
    attachments: bool = False
    relationships: bool = False


class ProviderSelection(BaseModel):
    mode: ExecutionMode = ExecutionMode.LEGACY
    providers: tuple[ProviderName, ...] = ()
    reason: str = "LEGACY_PASSTHROUGH"
    structured_query: StructuredQuery | None = None
    available_providers: tuple[ProviderName, ...] = ()


class StructuredQuery(BaseModel):
    operation: StructuredOperation
    provider: ProviderName
    filters: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    group_by: str | None = None
    section_kind: str | None = None
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=500)


class EvidenceEnvelope(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    provider: ProviderName
    project_id: str
    source_type: str
    source_id: str
    source_url: str | None = None
    locator: str | None = None
    access_policy_id: str
    source_version: str = ""
    event_date: str | None = None
    current: bool = True
    authority: str = ""
    score: float = 0.0
    document: Document


class StructuredResult(BaseModel):
    operation: StructuredOperation
    provider: ProviderName
    complete: bool
    snapshot_at: str | None = None
    total: int = 0
    rows: tuple[dict[str, Any], ...] = ()
    groups: dict[str, int] = Field(default_factory=dict)
    evidence: tuple[EvidenceEnvelope, ...] = ()
    degradation: tuple[str, ...] = ()
    applied_filter_rule: str | None = None
    clarification_options: tuple[str, ...] = ()


class ProviderFailure(BaseModel):
    provider: ProviderName
    code: str
    retryable: bool = False
    detail: str = ""


class FusionResult(BaseModel):
    evidence: tuple[EvidenceEnvelope, ...] = ()
    failures: tuple[ProviderFailure, ...] = ()
    complete: bool = True


class ProviderAdapter(ABC):
    name: ProviderName

    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    async def retrieve(self, query: str) -> tuple[EvidenceEnvelope, ...]: ...

    @abstractmethod
    async def lookup(self, identifiers: tuple[str, ...]) -> tuple[EvidenceEnvelope, ...]: ...

    @abstractmethod
    async def aggregate(self, query: StructuredQuery) -> StructuredResult: ...

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def freshness(self) -> str | None: ...
