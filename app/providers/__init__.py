"""Pluggable, access-scoped evidence providers for the RAG workflow."""

from app.providers.contracts import (
    EvidenceEnvelope,
    ExecutionMode,
    FusionResult,
    ProviderCapabilities,
    ProviderFailure,
    ProviderName,
    ProviderSelection,
    StructuredOperation,
    StructuredQuery,
    StructuredResult,
)
from app.providers.registry import ProviderRegistry

__all__ = [
    "EvidenceEnvelope",
    "ExecutionMode",
    "FusionResult",
    "ProviderCapabilities",
    "ProviderFailure",
    "ProviderName",
    "ProviderRegistry",
    "ProviderSelection",
    "StructuredOperation",
    "StructuredQuery",
    "StructuredResult",
]
