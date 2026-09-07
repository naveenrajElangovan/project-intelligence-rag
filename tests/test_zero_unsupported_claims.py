import asyncio

from langchain_core.documents import Document

from app.grounding_contract import evidence_facts, render_structured_facts, resolve_request, validate_output
from app.llm import GroundedAnswer
from app.models import AnswerStatus, Coverage, RagRequest, RagResponse, SourceReference
from app.source_policy import (
    SourceIntentDenied,
    SourcePolicy,
    SourcePolicyRegistry,
    UnsupportedSourceCategory,
    deduplicate_authoritative_versions,
)
from app.workflow_nodes.retrieval import RetrievalNodesMixin
from app.workflow_nodes.planning import (
    _single_record_details_requested,
    _single_record_subject,
)
from app.workflow_support.fail_closed import apply_output_gate


def _document(text: str = "The status is open.", **metadata: object) -> Document:
    values = {
        "project_id": "DEMO",
        "access_policy_id": "project:DEMO",
        "source_type": "RECORD",
        "source_id": "record-1",
        "parent_id": "record-1",
        "source_version": "1",
        "observed_at": "2026-01-01T00:00:00Z",
        "chunk_id": "chunk-1",
    }
    values.update(metadata)
    return Document(page_content=text, metadata=values)


def test_resolved_request_captures_shape_entities_and_completeness() -> None:
    resolved = resolve_request(
        "Compare all fields for ITEM-42 with ITEM-43 using the latest records",
        intent="COMPARE",
        allowed_source_categories=("record",),
        known_entities=(),
    )

    assert resolved.allowed_source_categories == ["RECORD"]
    assert {entity.canonical_id for entity in resolved.referenced_entities} == {
        "item-42",
        "item-43",
    }
    assert resolved.expected_answer_shape == "COMPARISON"
    assert resolved.completeness.all_items
    assert resolved.completeness.latest
    assert resolved.completeness.compare


def test_full_single_entity_request_is_not_an_exhaustive_inventory() -> None:
    resolved = resolve_request(
        "send me one full event details from POS application",
        intent="DELIVERY",
        allowed_source_categories=("RECORD",),
    )

    assert not resolved.completeness.all_items
    assert _single_record_details_requested(resolved.standalone_request)
    assert _single_record_subject(resolved.standalone_request) == "event pos application"


def test_named_event_all_parameters_requires_exhaustive_field_coverage() -> None:
    resolved = resolve_request(
        "Give me all LOGIN_POS_EVENT parameters",
        intent="STRUCTURED_ENTITY",
        allowed_source_categories=("RECORD",),
    )

    assert not resolved.completeness.all_items
    assert resolved.completeness.all_fields

    report = validate_output(
        resolved_request=resolved,
        documents=[_document("event_type and session_id")],
        generated=GroundedAnswer(
            answer="| Field | Source |\n|---|---|\n| event_type | [SOURCE 1] |",
            citations=[1],
        ),
        semantically_supported=True,
        required_policy="project:DEMO",
        expected_fields=("event_type", "session_id"),
        field_coverage_missing=("session_id",),
    )

    assert not report.requested_coverage_complete
    assert report.failure_reason == "REQUESTED_COVERAGE_INCOMPLETE"


def test_source_registry_rejects_unknown_and_disallowed_routes() -> None:
    registry = SourcePolicyRegistry(
        [SourcePolicy("RECORD", frozenset({"LOOKUP"}))]
    )

    assert registry.select("LOOKUP", ("record",)) == ("RECORD",)
    try:
        registry.select("SUMMARIZE", ("record",))
    except SourceIntentDenied:
        pass
    else:
        raise AssertionError("intent policy must fail closed")
    try:
        registry.select("LOOKUP", ("unrelated",))
    except UnsupportedSourceCategory:
        pass
    else:
        raise AssertionError("unknown categories must never be fallback routes")


def test_output_gate_rejects_an_uncited_atomic_claim() -> None:
    resolved = resolve_request(
        "What is the status?", intent="LOOKUP", allowed_source_categories=("RECORD",)
    )
    report = validate_output(
        resolved_request=resolved,
        documents=[_document()],
        generated=GroundedAnswer(answer="The status is open.", citations=[]),
        semantically_supported=True,
        required_policy="project:DEMO",
    )

    assert not report.all_claims_supported
    assert report.failure_reason == "UNSUPPORTED_CLAIM"


def test_explicit_derived_claim_requires_visible_reproducible_rule() -> None:
    resolved = resolve_request(
        "What follows from the records?",
        intent="LOOKUP",
        allowed_source_categories=("RECORD",),
    )
    ordinary_prose = validate_output(
        resolved_request=resolved,
        documents=[_document()],
        generated=GroundedAnswer(
            answer="Therefore the operation is safe [SOURCE 1].", citations=[1]
        ),
        semantically_supported=True,
        required_policy="project:DEMO",
    )
    valid = validate_output(
        resolved_request=resolved,
        documents=[_document()],
        generated=GroundedAnswer(
            answer=(
                "Inference (status open implies work remains): work remains "
                "[SOURCE 1]."
            ),
            citations=[1],
        ),
        semantically_supported=True,
        required_policy="project:DEMO",
    )

    assert ordinary_prose.failure_reason is None
    assert valid.failure_reason is None


def test_direct_grounded_prose_may_contain_therefore() -> None:
    resolved = resolve_request(
        "What is the status?", intent="LOOKUP", allowed_source_categories=("RECORD",)
    )

    report = validate_output(
        resolved_request=resolved,
        documents=[_document("The status is open, therefore work remains.")],
        generated=GroundedAnswer(
            answer="The status is open; therefore work remains [SOURCE 1].",
            citations=[1],
        ),
        semantically_supported=True,
        required_policy="project:DEMO",
    )

    assert report.failure_reason is None


def test_output_gate_rejects_scope_permission_and_coverage_failures() -> None:
    resolved = resolve_request(
        "List all records", intent="LIST", allowed_source_categories=("RECORD",)
    )
    answer = GroundedAnswer(answer="One record exists [SOURCE 1].", citations=[1])

    unauthorized = validate_output(
        resolved_request=resolved,
        documents=[_document(access_policy_id="project:OTHER")],
        generated=answer,
        semantically_supported=True,
        required_policy="project:DEMO",
        expected_identifiers=("one", "two"),
    )
    assert unauthorized.failure_reason == "PERMISSIONS_NOT_SATISFIED"

    wrong_scope = validate_output(
        resolved_request=resolved,
        documents=[_document(source_type="UNRELATED")],
        generated=answer,
        semantically_supported=True,
        required_policy="project:DEMO",
        expected_identifiers=("one",),
    )
    assert wrong_scope.failure_reason == "SOURCE_SCOPE_VIOLATION"

    incomplete = validate_output(
        resolved_request=resolved,
        documents=[_document(entity_key="one")],
        generated=answer,
        semantically_supported=True,
        required_policy="project:DEMO",
        expected_identifiers=("one", "two"),
    )
    assert incomplete.failure_reason == "REQUESTED_COVERAGE_INCOMPLETE"


def test_output_gate_accepts_complete_answer_with_parent_document_keys() -> None:
    resolved = resolve_request(
        "List all records", intent="LIST", allowed_source_categories=("RECORD",)
    )
    documents = [
        _document("One", entity_key="parent-record", chunk_id="chunk-1"),
        _document(
            "Two",
            entity_key="parent-record",
            source_id="record-2",
            chunk_id="chunk-2",
        ),
    ]

    report = validate_output(
        resolved_request=resolved,
        documents=documents,
        generated=GroundedAnswer(
            answer="- one [SOURCE 1]\n- two [SOURCE 2]", citations=[1, 2]
        ),
        semantically_supported=True,
        required_policy="project:DEMO",
        expected_identifiers=("one", "two"),
    )

    assert report.requested_coverage_complete
    assert report.failure_reason is None


def test_output_gate_does_not_trust_keys_when_answer_omits_item() -> None:
    resolved = resolve_request(
        "List all records", intent="LIST", allowed_source_categories=("RECORD",)
    )
    documents = [
        _document("One", entity_key="one", chunk_id="chunk-1"),
        _document("Two", entity_key="two", source_id="record-2", chunk_id="chunk-2"),
    ]

    report = validate_output(
        resolved_request=resolved,
        documents=documents,
        generated=GroundedAnswer(answer="- one [SOURCE 1]", citations=[1]),
        semantically_supported=True,
        required_policy="project:DEMO",
        expected_identifiers=("one", "two"),
    )

    assert not report.requested_coverage_complete
    assert report.failure_reason == "REQUESTED_COVERAGE_INCOMPLETE"


def test_output_gate_treats_missing_population_contract_as_unknown() -> None:
    resolved = resolve_request(
        "List all records", intent="LIST", allowed_source_categories=("RECORD",)
    )

    report = validate_output(
        resolved_request=resolved,
        documents=[_document("One")],
        generated=GroundedAnswer(answer="- one [SOURCE 1]", citations=[1]),
        semantically_supported=True,
        required_policy="project:DEMO",
        expected_identifiers=(),
    )

    assert report.requested_coverage_complete
    assert report.failure_reason is None


def test_output_gate_consumes_workflow_coverage_result() -> None:
    resolved = resolve_request(
        "List all records", intent="LIST", allowed_source_categories=("RECORD",)
    )
    documents = [
        _document("One", chunk_id="chunk-1"),
        _document("Two", source_id="record-2", chunk_id="chunk-2"),
    ]

    report = validate_output(
        resolved_request=resolved,
        documents=documents,
        generated=GroundedAnswer(
            answer="- one [SOURCE 1]\n- two [SOURCE 2]", citations=[1, 2]
        ),
        semantically_supported=True,
        required_policy="project:DEMO",
        expected_identifiers=("one", "two"),
        coverage_missing=("two",),
    )

    assert not report.requested_coverage_complete
    assert report.failure_reason == "REQUESTED_COVERAGE_INCOMPLETE"


def test_unknown_coverage_is_published_with_an_explicit_limitation() -> None:
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="List all records",
        accessPolicyIds=["project:DEMO"],
    )
    resolved = resolve_request(
        request.question, intent="LIST", allowed_source_categories=("RECORD",)
    )
    state = {
        "documents": [_document("One")],
        "generated": GroundedAnswer(
            answer="- one [SOURCE 1]", citations=[1], missing_information=[]
        ),
        "grounded": True,
        "coverage_expected_identifiers": (),
        "coverage_missing": (),
    }

    apply_output_gate(state, request, resolved, state["generated"])

    assert state["grounded"]
    assert state["coverage_partial"]
    assert "authoritative population contract" in state["generated"].missing_information[0]


def test_unknown_coverage_limitation_uses_the_response_language() -> None:
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Lista todos los registros",
        accessPolicyIds=["project:DEMO"],
    )
    resolved = resolve_request(
        request.question, intent="LIST", allowed_source_categories=("RECORD",)
    )
    state = {
        "documents": [_document("Uno")],
        "generated": GroundedAnswer(
            answer="- uno [SOURCE 1]", citations=[1], missing_information=[]
        ),
        "grounded": True,
        "language": "es",
        "coverage_expected_identifiers": (),
        "coverage_missing": (),
    }

    apply_output_gate(state, request, resolved, state["generated"])

    note = state["generated"].missing_information[0]
    assert "contrato de población" in note
    assert "authoritative" not in note


def test_gate_prunes_uncited_claim_and_keeps_grounded_sibling() -> None:
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="What is the status?",
        accessPolicyIds=["project:DEMO"],
    )
    resolved = resolve_request(
        request.question, intent="LOOKUP", allowed_source_categories=("RECORD",)
    )
    state = {
        "documents": [_document("The status is open.")],
        "generated": GroundedAnswer(
            answer=(
                "The status is open [SOURCE 1]. "
                "Fabricated `ITEM-999` is closed."
            ),
            citations=[1],
            missing_information=[],
        ),
        "grounded": True,
        "coverage_expected_identifiers": (),
        "coverage_missing": (),
    }

    apply_output_gate(state, request, resolved, state["generated"])

    assert state["grounded"]
    assert "status is open" in state["generated"].answer
    assert "ITEM-999" not in state["generated"].answer
    assert state["generated"].missing_information


def test_equal_authority_current_values_conflict_but_newer_wins() -> None:
    resolved = resolve_request(
        "What is the current status?",
        intent="LOOKUP",
        allowed_source_categories=("RECORD",),
    )
    answer = GroundedAnswer(
        answer="The current status is closed [SOURCE 2].", citations=[2]
    )
    old = _document(
        "open", field_path="status", normalized_value="open", observed_at="2025-01-01"
    )
    new = _document(
        "closed",
        source_id="record-2",
        chunk_id="chunk-2",
        field_path="status",
        normalized_value="closed",
        observed_at="2026-01-01",
    )
    resolved_report = validate_output(
        resolved_request=resolved,
        documents=[old, new],
        generated=answer,
        semantically_supported=True,
        required_policy="project:DEMO",
    )
    assert resolved_report.conflicts_resolved

    conflicting = new.model_copy(deep=True)
    conflicting.page_content = "blocked"
    conflicting.metadata["source_id"] = "record-3"
    conflicting.metadata["chunk_id"] = "chunk-3"
    conflicting.metadata["normalized_value"] = "blocked"
    conflict_report = validate_output(
        resolved_request=resolved,
        documents=[new, conflicting],
        generated=answer,
        semantically_supported=True,
        required_policy="project:DEMO",
    )
    assert conflict_report.failure_reason == "UNRESOLVED_SOURCE_CONFLICT"


def test_authoritative_version_deduplication_preserves_parent_chunks() -> None:
    registry = SourcePolicyRegistry(
        [SourcePolicy("RECORD", authority_priority=10)]
    )
    old = _document(source_version="1", chunk_id="old")
    first = _document(source_version="2", chunk_id="new-1")
    second = _document("More fields", source_version="2", chunk_id="new-2")

    selected = deduplicate_authoritative_versions([old, first, second], registry)

    assert [item.metadata["chunk_id"] for item in selected] == ["new-1", "new-2"]


def test_structured_fields_are_rendered_deterministically() -> None:
    document = _document(
        "ignored narrative",
        canonical_entity_id="item-42",
        field_path="status",
        normalized_value="OPEN",
    )

    answer = render_structured_facts(evidence_facts([document]))

    assert answer is not None
    assert "| `item-42` | `status` | open | [SOURCE 1] |" in answer.answer
    assert answer.citations == [1]


def test_matching_chunk_reconstructs_complete_parent_version() -> None:
    first = _document("first", chunk_id="one", chunk_ordinal=0)
    second = _document("second", chunk_id="two", chunk_ordinal=1)

    class Retriever:
        async def ainvoke_source_siblings(self, parent_ids, source_types):
            assert parent_ids == ("record-1",)
            assert source_types == ("RECORD",)
            return [second, first]

    workflow = RetrievalNodesMixin()
    workflow._retriever = Retriever()
    reconstructed = asyncio.run(
        workflow._reconstruct_parent_records([second], ("RECORD",))
    )

    assert [item.metadata["chunk_id"] for item in reconstructed] == ["one", "two"]


def test_response_adds_new_contract_without_removing_legacy_sources() -> None:
    source = SourceReference(type="RECORD", title="One", reference="1")
    response = RagResponse(
        status=AnswerStatus.ANSWERED,
        answer="Done",
        confidence="HIGH",
        projectId="DEMO",
        sources=[source],
        missingInformation=[],
        coverage=Coverage.COMPLETE,
    )

    assert response.sources == response.citations
    assert response.model_dump(by_alias=True)["status"] == "ANSWERED"

    unavailable = RagResponse(
        status=AnswerStatus.INSUFFICIENT_EVIDENCE,
        answer="The requested fact could not be verified.",
        confidence="NONE",
        projectId="DEMO",
        sources=[source],
        missingInformation=[],
        coverage=Coverage.PARTIAL,
    )
    assert unavailable.sources == [source]
    assert unavailable.citations == []
