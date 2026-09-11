from __future__ import annotations

from app.providers.contracts import ProviderAdapter, ProviderName
from app.providers.indexed import IndexedProviderAdapter


class ProviderRegistry:
    def __init__(self, adapters: tuple[ProviderAdapter, ...]) -> None:
        self._adapters = {adapter.name: adapter for adapter in adapters}

    @classmethod
    def indexed(
        cls, *, project_id: str, retriever: object, enabled: tuple[ProviderName, ...]
    ) -> "ProviderRegistry":
        return cls(tuple(IndexedProviderAdapter(name, project_id, retriever) for name in enabled))

    @property
    def names(self) -> tuple[ProviderName, ...]:
        return tuple(self._adapters)

    def get(self, name: ProviderName) -> ProviderAdapter:
        return self._adapters[name]
