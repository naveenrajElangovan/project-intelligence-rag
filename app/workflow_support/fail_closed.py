"""Fail-closed request and final-response decisions for the workflow."""

from __future__ import annotations

import re

from app.grounding_contract import (
    evidence_facts,
    grounded_claims,
    resolve_request,
    validate_output,
)
from app.llm import GroundedAnswer
from app.models import RagRequest, RagResponse, ResolvedRequest
from app.telemetry import stage_complete, started
from app.workflow_support.answer_structure import (
    material_claims,
    prune_unsupported_claims,
)
from app.workflow_support.conversation import _conversation_resolution_decision
from app.workflow_support.query_analysis import resolve_response_language


def clarification_response(
    request: RagRequest, known_entities: tuple[str, ...]
) -> RagResponse | None:
    normalized = " ".join(re.findall(r"[a-z0-9]+", request.question.casefold()))
    # Underscores are word separators to the tokenizer above, so an underscored
    # identifier arrives here as separate words and trips the overloaded-record
    # guard on whichever of them happens to be an overloaded noun. The identifier
    # is precisely what makes the question unambiguous, so a question that names
    # one is never a candidate for clarification -- neither for the overloaded
    # record below nor for the unresolved reference after it.
    explicit_identifier = bool(
        re.search(r"\b[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+\b", request.question)
    )
    overloaded_record = bool(
        re.search(r"\b(?:tickets?|boletos?)\b", normalized)
    ) and not explicit_identifier
    delivery_context = bool(
        re.search(
            r"\b(?:jira|issue|bug|sprint|release|priority|status|assignee|backlog|"
            r"incidencia|error|estado|prioridad|entrega)\b",
            normalized,
        )
    )
    document_context = bool(
        re.search(
            r"\b(?:print|reprint|printer|receipt|paper|imprimir|reimprimir|"
            r"impresora|recibo|comprobante|papel)\b",
            normalized,
        )
    )
    if overloaded_record and not delivery_context and not document_context:
        language = resolve_response_language(request.question)
        return RagResponse(
            status="NEEDS_CLARIFICATION",
            answer=(
                "¿Te refieres a un elemento de trabajo o a un comprobante/documento?"
                if language == "es"
                else "Do you mean a work item or a receipt/document?"
            ),
            confidence="NONE",
            projectId=request.project_id,
            sources=[],
            missingInformation=[],
            evidenceStatus="NOT_APPLICABLE",
            contextQuality="NOT_APPLICABLE",
            coverage="NOT_APPLICABLE",
            failureReason="AMBIGUOUS_SOURCE_FAMILY",
        )
    needed, _reason = _conversation_resolution_decision(request.question)
    named_entity = any(
        re.search(
            rf"(?<![A-Za-z0-9_]){re.escape(str(entity))}(?![A-Za-z0-9_])",
            request.question,
            re.IGNORECASE,
        )
        for entity in known_entities
        if str(entity).strip()
    )
    if (
        not needed
        or explicit_identifier
        or named_entity
        or request.conversation_context.active_subject.strip()
        or request.conversation_history
    ):
        return None
    language = resolve_response_language(request.question)
    return RagResponse(
        status="NEEDS_CLARIFICATION",
        answer=(
            "¿A qué tema o entidad te refieres?"
            if language == "es"
            else "Which topic or entity are you referring to?"
        ),
        confidence="NONE",
        projectId=request.project_id,
        sources=[],
        missingInformation=[],
        evidenceStatus="NOT_APPLICABLE",
        contextQuality="NOT_APPLICABLE",
        coverage="NOT_APPLICABLE",
        failureReason="AMBIGUOUS_FOLLOWUP",
    )


def resolved_request_for_state(
    state: dict[str, object], request: RagRequest, known_entities: tuple[str, ...]
) -> ResolvedRequest:
    return state.get("resolved_request") or resolve_request(
        state.get("resolved_question", request.question),
        intent=state.get("query_intent", "DIRECT"),
        allowed_source_categories=state.get("source_types", ()),
        known_entities=known_entities,
    )


def apply_output_gate(
    state: dict[str, object],
    request: RagRequest,
    resolved: ResolvedRequest,
    generated: GroundedAnswer | None,
) -> None:
    documents = state.get("documents", [])
    if not documents or generated is None or state.get("grounded") is False:
        return
    began = started()
    language = state.get("language") or resolve_response_language(request.question)
    expected_identifiers = tuple(state.get("coverage_expected_identifiers", ()))
    coverage_missing = (
        tuple(state.get("coverage_missing", ()))
        if "coverage_missing" in state
        else None
    )
    expected_fields = tuple(state.get("coverage_expected_fields", ()))
    field_coverage_missing = (
        tuple(state.get("coverage_missing_fields", ()))
        if "coverage_missing_fields" in state
        else None
    )
    coverage_unknown = bool(
        (resolved.completeness.all_items and not expected_identifiers)
        or (resolved.completeness.all_fields and not expected_fields)
    )
    validation = validate_output(
        resolved_request=resolved,
        documents=documents,
        generated=generated,
        semantically_supported=True,
        required_policy=f"project:{request.project_id}",
        authorized_policies=request.access_policy_ids,
        expected_identifiers=expected_identifiers,
        coverage_missing=coverage_missing,
        expected_fields=expected_fields,
        field_coverage_missing=field_coverage_missing,
    )
    initial_reason = validation.failure_reason
    removed_claims = 0
    if validation.failure_reason in {"UNSUPPORTED_CLAIM", "INVALID_DERIVATION"}:
        facts_for_pruning = evidence_facts(documents)
        parsed_claims = grounded_claims(generated, facts_for_pruning)
        original_claims = material_claims(generated.answer)
        invalid = {
            original.text
            for original, claim in zip(original_claims, parsed_claims, strict=True)
            if not claim.supporting_fact_ids
            or (claim.claim_type == "DERIVED" and not claim.derivation_rule)
        }
        pruned_answer, removed_claims = prune_unsupported_claims(
            generated.answer, {" ".join(value.split()).casefold() for value in invalid}
        )
        if removed_claims and material_claims(pruned_answer):
            note = (
                (
                    "Se eliminó una afirmación sin respaldo."
                    if removed_claims == 1
                    else f"Se eliminaron {removed_claims} afirmaciones sin respaldo."
                )
                if language == "es"
                else (
                    "One unsupported statement was removed."
                    if removed_claims == 1
                    else f"{removed_claims} unsupported statements were removed."
                )
            )
            generated = generated.model_copy(
                update={
                    "answer": pruned_answer,
                    "citations": list(
                        dict.fromkeys(
                            int(value)
                            for value in re.findall(r"\[SOURCE (\d+)\]", pruned_answer)
                        )
                    ),
                    "missing_information": [
                        *generated.missing_information,
                        note,
                    ],
                }
            )
            validation = validate_output(
                resolved_request=resolved,
                documents=documents,
                generated=generated,
                semantically_supported=True,
                required_policy=f"project:{request.project_id}",
                authorized_policies=request.access_policy_ids,
                expected_identifiers=expected_identifiers,
                coverage_missing=coverage_missing,
                expected_fields=expected_fields,
                field_coverage_missing=field_coverage_missing,
            )
            state["generated"] = generated
    if coverage_unknown:
        contract_kind = (
            "field definition"
            if resolved.completeness.all_fields
            else "population contract"
        )
        if language == "es":
            contract_kind = (
                "definición de campos"
                if resolved.completeness.all_fields
                else "contrato de población"
            )
            note = (
                "La evidencia disponible respalda estos detalles, pero no había una "
                f"{contract_kind} autoritativa para verificar que el conjunto fuera exhaustivo."
            )
        else:
            note = (
                "The available evidence supports these details, but no authoritative "
                f"{contract_kind} was available to verify that the set is exhaustive."
            )
        if note not in generated.missing_information:
            generated = generated.model_copy(
                update={
                    "missing_information": [*generated.missing_information, note]
                }
            )
            state["generated"] = generated
        state["coverage_partial"] = True
    elif validation.failure_reason == "REQUESTED_COVERAGE_INCOMPLETE":
        if resolved.completeness.all_fields:
            missing = tuple(field_coverage_missing or ())
            note = (
                f"Se verificaron {len(expected_fields) - len(missing)} de "
                f"{len(expected_fields)} campos declarados; no verificados: {', '.join(missing)}."
                if language == "es"
                else f"{len(expected_fields) - len(missing)} of {len(expected_fields)} "
                f"declared fields were verified; not verified: {', '.join(missing)}."
            )
        else:
            missing = tuple(coverage_missing or ())
            note = (
                f"Se verificaron {len(expected_identifiers) - len(missing)} de "
                f"{len(expected_identifiers)} identificadores; no verificados: "
                f"{', '.join(missing)}."
                if language == "es"
                else f"{len(expected_identifiers) - len(missing)} of "
                f"{len(expected_identifiers)} identifiers were verified; not verified: "
                f"{', '.join(missing)}."
            )
        if missing and note not in generated.missing_information:
            generated = generated.model_copy(
                update={
                    "missing_information": [*generated.missing_information, note]
                }
            )
            state["generated"] = generated
        state["coverage_partial"] = True
    facts = evidence_facts(documents) if validation.permissions_satisfied else []
    claims = grounded_claims(generated, facts) if facts else []
    stage_complete(
        "output_gate",
        request.project_id,
        began,
        input_count=len(claims),
        output_count=1 if validation.failure_reason is None else 0,
        reason_code=(
            "VALIDATED_COVERAGE_UNKNOWN"
            if coverage_unknown and validation.failure_reason is None
            else "CLAIMS_REMOVED_SUPPORTED"
            if removed_claims and validation.failure_reason is None
            else validation.failure_reason or "VALIDATED"
        ),
        model_provider="deterministic",
        model_name="claim-evidence-output-gate",
        model_profile="grounding",
        language=state.get("language", "und"),
        extra={
            "resolved_intent": resolved.intent,
            "selected_source_categories": ",".join(
                resolved.allowed_source_categories
            ),
            "evidence_fact_ids": ",".join(fact.fact_id for fact in facts),
            "claim_count": len(claims),
            "coverage_complete": validation.requested_coverage_complete,
            "conflicts_resolved": validation.conflicts_resolved,
            "permissions_satisfied": validation.permissions_satisfied,
            "freshness_satisfied": validation.freshness_satisfied,
            "initial_reason_code": initial_reason or "VALIDATED",
            "final_reason_code": validation.failure_reason or "VALIDATED",
            "claims_removed": removed_claims,
            "coverage_unknown": coverage_unknown,
            "field_coverage_expected": len(expected_fields),
            "field_coverage_missing": len(field_coverage_missing or ()),
        },
    )
    if validation.failure_reason == "REQUESTED_COVERAGE_INCOMPLETE":
        return
    if validation.failure_reason:
        state["output_gate_applied"] = True
        state["grounded"] = False
        state["grounding_reason"] = validation.failure_reason
