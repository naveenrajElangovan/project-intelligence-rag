"""Domain-independent request, evidence, claim, and output-gate contracts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from typing import Literal

from langchain_core.documents import Document
from pydantic import BaseModel, Field

from app.llm import GroundedAnswer
from app.models import (
    CompletenessRequirements,
    ResolvedEntity,
    ResolvedRequest,
)
from app.workflow_support.answer_structure import material_claims
from app.workflow_support.inventory_intent import (
    is_exhaustive_entity_detail_question,
    is_inventory_question,
)


class EvidenceFact(BaseModel):
    fact_id: str = Field(alias="factId")
    canonical_entity_id: str = Field(alias="canonicalEntityId")
    field_path: str | None = Field(default=None, alias="fieldPath")
    source_span: str | None = Field(default=None, alias="sourceSpan")
    normalized_value: str = Field(alias="normalizedValue")
    source_id: str = Field(alias="sourceId")
    source_category: str = Field(alias="sourceCategory")
    authority: int = 0
    version: str = ""
    observed_at: str = Field(default="", alias="observedAt")


class GroundedClaim(BaseModel):
    text: str
    supporting_fact_ids: list[str] = Field(alias="supportingFactIds")
    claim_type: Literal["DIRECT", "DERIVED"] = Field(default="DIRECT", alias="claimType")
    derivation_rule: str | None = Field(default=None, alias="derivationRule")


class ValidationReport(BaseModel):
    all_claims_supported: bool = Field(alias="allClaimsSupported")
    requested_coverage_complete: bool = Field(alias="requestedCoverageComplete")
    conflicts_resolved: bool = Field(alias="conflictsResolved")
    permissions_satisfied: bool = Field(alias="permissionsSatisfied")
    freshness_satisfied: bool = Field(alias="freshnessSatisfied")
    failure_reason: str | None = Field(default=None, alias="failureReason")


_SOURCE_MARKER = re.compile(r"\[SOURCE (\d+)\]")
_IDENTIFIER = re.compile(r"(?<![\w])(?=[A-Za-z0-9._:/-]*[A-Za-z])(?=[A-Za-z0-9._:/-]*\d)[A-Za-z0-9]+(?:[._:/-][A-Za-z0-9]+)+(?![\w])")
_INFERENCE = re.compile(r"^\s*(?:[-*]\s*)?Inference\s*\(([^)]+)\)\s*:", re.IGNORECASE)


def _fact_freshness(fact: EvidenceFact) -> tuple[str, tuple[int, ...], str]:
    return (
        fact.observed_at,
        tuple(int(value) for value in re.findall(r"\d+", fact.version)),
        fact.version.casefold(),
    )


def _answer_contains_identifier(answer: str, identifier: str) -> bool:
    """Match an expected identifier in the rendered answer, not retrieval metadata."""

    candidate = identifier.strip()
    if not candidate:
        return False
    return bool(
        re.search(
            rf"(?<![\w]){re.escape(candidate)}(?![\w])",
            answer,
            re.IGNORECASE,
        )
    )


def resolve_request(
    standalone_request: str,
    *,
    intent: str,
    allowed_source_categories: Iterable[str],
    known_entities: Iterable[str] = (),
) -> ResolvedRequest:
    """Build a bounded request using only text and server-selected policy data."""

    normalized = " ".join(standalone_request.split())
    lower = normalized.casefold()
    entities: dict[str, ResolvedEntity] = {}
    for value in known_entities:
        candidate = str(value).strip()
        if candidate and re.search(
            rf"(?<![\w]){re.escape(candidate)}(?![\w])", normalized, re.IGNORECASE
        ):
            canonical = candidate.casefold()
            entities[canonical] = ResolvedEntity(
                value=candidate, canonicalId=canonical
            )
    for candidate in _IDENTIFIER.findall(normalized):
        canonical = candidate.casefold()
        entities.setdefault(
            canonical,
            ResolvedEntity(type="identifier", value=candidate, canonicalId=canonical),
        )
    exhaustive = is_inventory_question(normalized)
    exhaustive_fields = is_exhaustive_entity_detail_question(normalized)
    latest = bool(re.search(r"\b(?:latest|current|newest|most recent|actual|reciente)\b", lower))
    compare = bool(re.search(r"\b(?:compare|comparison|versus|vs\.?|differ|comparar|comparacion)\b", lower))
    if compare:
        shape = "COMPARISON"
    elif re.search(r"\b(?:schema|fields?|parameters?|columns?|table|tabla)\b", lower):
        shape = "STRUCTURED"
    elif re.search(r"\b(?:list|enumerate|lista|listar)\b", lower):
        shape = "LIST"
    else:
        shape = "NARRATIVE"
    return ResolvedRequest(
        standaloneRequest=normalized,
        intent=intent or "DIRECT",
        operation="ANSWER",
        referencedEntities=list(entities.values()),
        allowedSourceCategories=list(
            dict.fromkeys(
                str(value).strip().upper()
                for value in allowed_source_categories
                if str(value).strip()
            )
        ),
        expectedAnswerShape=shape,
        completeness=CompletenessRequirements(
            **{"all": exhaustive, "allFields": exhaustive_fields},
            latest=latest,
            compare=compare,
        ),
    )


def evidence_facts(documents: Sequence[Document]) -> list[EvidenceFact]:
    """Create stable evidence records without interpreting source prose."""

    facts: list[EvidenceFact] = []
    for index, document in enumerate(documents, start=1):
        metadata = document.metadata
        source_id = str(
            metadata.get("source_id") or metadata.get("reference") or metadata.get("chunk_id") or index
        )
        entity_id = str(
            metadata.get("canonical_entity_id")
            or metadata.get("entity_key")
            or metadata.get("parent_id")
            or source_id
        )
        value = str(metadata.get("normalized_value") or "") or " ".join(
            document.page_content.split()
        )
        digest = hashlib.sha256(
            f"{source_id}\0{metadata.get('source_version', '')}\0{metadata.get('chunk_id', index)}\0{value}".encode()
        ).hexdigest()[:24]
        facts.append(
            EvidenceFact(
                factId=f"fact:{digest}",
                canonicalEntityId=entity_id,
                fieldPath=str(metadata.get("field_path") or "") or None,
                sourceSpan=str(metadata.get("source_span") or metadata.get("locator") or "") or None,
                normalizedValue=value.casefold(),
                sourceId=source_id,
                sourceCategory=str(metadata.get("source_type") or "DOCUMENT").upper(),
                authority=int(metadata.get("authority") or 0),
                version=str(metadata.get("source_version") or ""),
                observedAt=str(metadata.get("observed_at") or ""),
            )
        )
    return facts


def grounded_claims(answer: GroundedAnswer, facts: Sequence[EvidenceFact]) -> list[GroundedClaim]:
    claims: list[GroundedClaim] = []
    for claim in material_claims(answer.answer):
        indexes = [int(value) for value in _SOURCE_MARKER.findall(claim.text)]
        inference = _INFERENCE.search(claim.text)
        claims.append(
            GroundedClaim(
                text=_SOURCE_MARKER.sub("", claim.text).strip(),
                supportingFactIds=[
                    facts[index - 1].fact_id for index in indexes if 1 <= index <= len(facts)
                ],
                claimType="DERIVED" if inference else "DIRECT",
                derivationRule=inference.group(1).strip() if inference else None,
            )
        )
    return claims


def render_structured_facts(facts: Sequence[EvidenceFact]) -> GroundedAnswer | None:
    """Render indexed structured values without a generative model."""

    rows: list[tuple[str, str, str, int]] = []
    seen: set[tuple[str, str, str]] = set()
    for index, fact in enumerate(facts, start=1):
        if not fact.field_path:
            continue
        identity = (
            fact.canonical_entity_id,
            fact.field_path,
            fact.normalized_value,
        )
        if identity in seen:
            continue
        seen.add(identity)
        rows.append((*identity, index))
    if not rows:
        return None
    lines = [
        "| Entity | Field | Value | Source |",
        "|---|---|---|---|",
        *(
            f"| `{entity}` | `{field}` | {value} | [SOURCE {source}] |"
            for entity, field, value, source in rows
        ),
    ]
    return GroundedAnswer(
        answer="\n".join(lines),
        citations=list(dict.fromkeys(source for *_values, source in rows)),
    )


def validate_output(
    *,
    resolved_request: ResolvedRequest,
    documents: Sequence[Document],
    generated: GroundedAnswer,
    semantically_supported: bool,
    required_policy: str,
    expected_identifiers: Sequence[str] = (),
    coverage_missing: Sequence[str] | None = None,
    expected_fields: Sequence[str] = (),
    field_coverage_missing: Sequence[str] | None = None,
) -> ValidationReport:
    """Final fail-closed check run after semantic grounding and before display."""

    facts = evidence_facts(documents)
    claims = grounded_claims(generated, facts)
    permissions_ok = all(
        document.metadata.get("access_policy_id") in (None, "", required_policy)
        for document in documents
    )
    allowed = set(resolved_request.allowed_source_categories)
    scope_ok = not allowed or all(
        fact.source_category == "DOCUMENT" or fact.source_category in allowed
        for fact in facts
    )
    # An answer that parses to no material claim asserts nothing, so there is
    # nothing here that could be unsupported. Requiring at least one claim made
    # "nothing to check" indistinguishable from "the check failed", and the
    # pruning path below has no sentence to remove, so the answer was discarded
    # whole. Emptiness is decided upstream, where retrieval and completeness can
    # see why there is no answer.
    claim_support_ok = all(claim.supporting_fact_ids for claim in claims)
    derivations_ok = all(
        claim.claim_type == "DIRECT"
        or (
            bool(claim.derivation_rule)
            and bool(claim.supporting_fact_ids)
        )
        for claim in claims
    )

    conflict_candidates: dict[tuple[str, str], list[EvidenceFact]] = {}
    for fact in facts:
        if fact.field_path:
            conflict_candidates.setdefault(
                (fact.canonical_entity_id, fact.field_path), []
            ).append(fact)
    unresolved_conflict = False
    for candidates in conflict_candidates.values():
        highest_authority = max(fact.authority for fact in candidates)
        authoritative = [
            fact for fact in candidates if fact.authority == highest_authority
        ]
        newest = max(_fact_freshness(fact) for fact in authoritative)
        current = [
            fact
            for fact in authoritative
            if _fact_freshness(fact) == newest
        ]
        if len({fact.normalized_value for fact in current}) > 1:
            unresolved_conflict = True
            break

    expected = tuple(
        dict.fromkeys(
            value.strip() for value in expected_identifiers if value.strip()
        )
    )
    expected_field_names = tuple(
        dict.fromkeys(value.strip() for value in expected_fields if value.strip())
    )
    if resolved_request.completeness.all_fields:
        if field_coverage_missing is not None:
            coverage_ok = not field_coverage_missing
        elif not expected_field_names:
            coverage_ok = True
        else:
            coverage_ok = all(
                _answer_contains_identifier(generated.answer, field)
                for field in expected_field_names
            )
    elif not resolved_request.completeness.all_items:
        coverage_ok = True
    elif coverage_missing is not None:
        coverage_ok = not coverage_missing
    elif not expected:
        # There is no authoritative population contract to compare against.
        # Unknown coverage is disclosed by the caller, not misreported as failed.
        coverage_ok = True
    else:
        coverage_ok = all(
            _answer_contains_identifier(generated.answer, identifier)
            for identifier in expected
        )
    freshness_ok = not resolved_request.completeness.latest or all(
        fact.version or fact.observed_at for fact in facts
    )
    if not permissions_ok:
        reason = "PERMISSIONS_NOT_SATISFIED"
    elif not scope_ok:
        reason = "SOURCE_SCOPE_VIOLATION"
    elif unresolved_conflict:
        reason = "UNRESOLVED_SOURCE_CONFLICT"
    elif not freshness_ok:
        reason = "FRESHNESS_NOT_VERIFIABLE"
    elif not coverage_ok:
        reason = "REQUESTED_COVERAGE_INCOMPLETE"
    elif not derivations_ok:
        reason = "INVALID_DERIVATION"
    elif not semantically_supported or not claim_support_ok:
        reason = "UNSUPPORTED_CLAIM"
    else:
        reason = None
    return ValidationReport(
        allClaimsSupported=semantically_supported and claim_support_ok,
        requestedCoverageComplete=coverage_ok,
        conflictsResolved=not unresolved_conflict,
        permissionsSatisfied=permissions_ok and scope_ok,
        freshnessSatisfied=freshness_ok,
        failureReason=reason,
    )
