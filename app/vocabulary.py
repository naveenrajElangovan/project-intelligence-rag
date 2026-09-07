from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable


VOCABULARY_RECORD_KIND = "__vocabulary__"


@dataclass(frozen=True, slots=True)
class CorpusVocabulary:
    """Project-owned vocabulary used only to specialize retrieval behavior."""

    entities: tuple[str, ...] = ()
    doc_categories: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    source_types: tuple[str, ...] = ()
    code_extensions: tuple[str, ...] = ()
    languages: tuple[str, ...] = ()
    intent_terms: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def entity_set(self) -> frozenset[str]:
        return frozenset(self.entities)

    def terms_for(self, intent: str) -> tuple[str, ...]:
        return next((terms for name, terms in self.intent_terms if name == intent), ())

    @classmethod
    def from_record(
        cls, metadata: dict[str, Any] | None, document: str | None = None
    ) -> "CorpusVocabulary":
        values: dict[str, Any] = {}
        if document:
            try:
                decoded = json.loads(document)
            except (TypeError, ValueError):
                decoded = None
            if isinstance(decoded, dict):
                values.update(decoded)
        values.update(metadata or {})
        if values.get("record_kind") != VOCABULARY_RECORD_KIND:
            return cls()
        return cls(
            entities=_normalized_values(values.get("entities"), casefold=True),
            doc_categories=_normalized_values(values.get("doc_categories"), casefold=True),
            providers=_normalized_values(values.get("providers"), upper=True),
            source_types=_normalized_values(values.get("source_types"), upper=True),
            code_extensions=_extensions(values.get("code_extensions")),
            languages=_normalized_values(values.get("languages"), casefold=True),
            intent_terms=_intent_terms(values.get("intent_terms")),
        )

    @classmethod
    def merge(cls, values: Iterable["CorpusVocabulary"]) -> "CorpusVocabulary":
        """Merge only vocabulary records already filtered to caller-visible policies."""

        vocabularies = tuple(values)
        merged = {
                field: tuple(
                    dict.fromkeys(
                        item
                        for vocabulary in vocabularies
                        for item in getattr(vocabulary, field)
                    )
                )
                for field in (
                    "entities",
                    "doc_categories",
                    "providers",
                    "source_types",
                    "code_extensions",
                    "languages",
                )
            }
        intent_names = tuple(
            dict.fromkeys(name for vocabulary in vocabularies for name, _ in vocabulary.intent_terms)
        )
        merged["intent_terms"] = tuple(
            (
                name,
                tuple(
                    dict.fromkeys(
                        term
                        for vocabulary in vocabularies
                        for intent, terms in vocabulary.intent_terms
                        if intent == name
                        for term in terms
                    )
                ),
            )
            for name in intent_names
        )
        return cls(**merged)


def _intent_terms(value: Any) -> tuple[tuple[str, tuple[str, ...]], ...]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return ()
    if not isinstance(value, dict):
        return ()
    return tuple(
        (str(intent).upper(), _normalized_values(terms, casefold=True))
        for intent, terms in sorted(value.items())
        if str(intent).strip() and _normalized_values(terms, casefold=True)
    )

def _raw_values(value: Any) -> Iterable[Any]:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except ValueError:
                decoded = None
            if isinstance(decoded, list):
                return decoded
        return stripped.split(",")
    if isinstance(value, (list, tuple, set, frozenset)):
        return value
    return ()


def _normalized_values(
    value: Any, *, casefold: bool = False, upper: bool = False
) -> tuple[str, ...]:
    normalized: list[str] = []
    for item in _raw_values(value):
        text = str(item).strip()
        if not text:
            continue
        text = text.casefold() if casefold else text.upper() if upper else text
        normalized.append(text)
    return tuple(dict.fromkeys(normalized))


def _extensions(value: Any) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            extension if extension.startswith(".") else f".{extension}"
            for extension in _normalized_values(value, casefold=True)
        )
    )
