"""Source routing policy independent of providers and business domains."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
import re

from langchain_core.documents import Document


class UnsupportedSourceCategory(ValueError):
    pass


class SourceIntentDenied(PermissionError):
    pass


@dataclass(frozen=True, slots=True)
class SourcePolicy:
    category: str
    permitted_intents: frozenset[str] = frozenset({"*"})
    authority_priority: int = 0
    freshness_field: str = "observed_at"
    access_control_required: bool = True

    def permits(self, intent: str) -> bool:
        return "*" in self.permitted_intents or intent.upper() in self.permitted_intents


class SourcePolicyRegistry:
    """Validates a route before retrieval; it never invents fallback categories."""

    def __init__(self, policies: Iterable[SourcePolicy]) -> None:
        self._policies = {
            policy.category.strip().upper(): policy
            for policy in policies
            if policy.category.strip()
        }

    @classmethod
    def from_categories(cls, categories: Iterable[str]) -> "SourcePolicyRegistry":
        return cls(
            SourcePolicy(category=str(category).strip().upper())
            for category in categories
            if str(category).strip()
        )

    def select(self, intent: str, requested: Iterable[str]) -> tuple[str, ...]:
        selected = tuple(
            dict.fromkeys(
                str(category).strip().upper()
                for category in requested
                if str(category).strip()
            )
        )
        for category in selected:
            policy = self._policies.get(category)
            if policy is None:
                raise UnsupportedSourceCategory(category)
            if not policy.permits(intent):
                raise SourceIntentDenied(f"{intent}:{category}")
        return selected

    def authority(self, category: str) -> int:
        policy = self._policies.get(category.strip().upper())
        return policy.authority_priority if policy else -1


def _freshness_key(document: Document) -> tuple[str, tuple[int, ...], str]:
    version = str(document.metadata.get("source_version") or "")
    return (
        str(document.metadata.get("observed_at") or ""),
        tuple(int(value) for value in re.findall(r"\d+", version)),
        version.casefold(),
    )


def deduplicate_authoritative_versions(
    documents: Sequence[Document], registry: SourcePolicyRegistry
) -> list[Document]:
    """Keep every chunk of the best source version for each canonical entity."""

    grouped: dict[str, list[Document]] = {}
    order: list[str] = []
    for document in documents:
        metadata = document.metadata
        entity = str(
            metadata.get("canonical_entity_id")
            or metadata.get("entity_key")
            or metadata.get("parent_id")
            or metadata.get("source_id")
            or metadata.get("chunk_id")
            or id(document)
        )
        if entity not in grouped:
            grouped[entity] = []
            order.append(entity)
        grouped[entity].append(document)

    selected: list[Document] = []
    for entity in order:
        candidates = grouped[entity]
        best_authority = max(
            int(document.metadata.get("authority") or registry.authority(
                str(document.metadata.get("source_type") or "")
            ))
            for document in candidates
        )
        authoritative = [
            document
            for document in candidates
            if int(document.metadata.get("authority") or registry.authority(
                str(document.metadata.get("source_type") or "")
            )) == best_authority
        ]
        newest = max(_freshness_key(document) for document in authoritative)
        selected.extend(
            document
            for document in authoritative
            if _freshness_key(document) == newest
        )
    return selected
