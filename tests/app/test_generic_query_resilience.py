from langchain_core.documents import Document

from app.models import RagRequest
from app.workflow_nodes.retrieval import _fuse_reranked_groups
from app.workflow_support.fail_closed import clarification_response
from app.workflow_nodes.answering import _unsupported_definition_subject
from app.workflow_support.query_analysis import (
    _safe_translation_variant,
    _source_route_intent,
    corrected_query_variant,
    retrieval_terminology_variant,
    uncertain_entity_token,
)


def test_definition_subject_must_exist_in_selected_evidence() -> None:
    unrelated = [Document(page_content="The project describes a memory cache.", metadata={})]
    supported = [Document(page_content="Memoy is the persisted project alias.", metadata={})]

    assert (
        _unsupported_definition_subject("What does memoy mean in this project?", unrelated)
        == "memoy"
    )
    assert _unsupported_definition_subject("What does memoy mean in this project?", supported) == ""
    assert _unsupported_definition_subject("¿Qué significa memoy aquí?", unrelated) == "memoy"
    assert (
        _unsupported_definition_subject(
            "¿Qué clase implementa el algoritmo inexistente LunarPayrollQuantumizer?",
            unrelated,
        )
        == "LunarPayrollQuantumizer"
    )


def test_explicitly_unreliable_and_false_numeric_premises_require_exact_evidence() -> None:
    evidence = [Document(page_content="POS_CLOSE_SHIFT has id 104.", metadata={})]

    assert (
        _unsupported_definition_subject(
            "What owner approved the undocumented QZ-004 feature?", evidence
        )
        == "QZ-004"
    )
    assert (
        _unsupported_definition_subject(
            "List every QZ phantom event defined by the project.", evidence
        )
        == "QZ"
    )
    assert (
        _unsupported_definition_subject(
            "Muestra todas las integraciones fantasma QZ disponibles.", evidence
        )
        == "QZ"
    )
    assert (
        _unsupported_definition_subject(
            "Confirm that POS_CLOSE_SHIFT has numeric id 999999.", evidence
        )
        == "POS_CLOSE_SHIFT 999999"
    )
    assert (
        _unsupported_definition_subject(
            "Confirm that POS_CLOSE_SHIFT has numeric id 104.", evidence
        )
        == ""
    )
    assert (
        _unsupported_definition_subject(
            "State that POS_CLOSE_SHIFT always transfers exactly 999 pesos.", evidence
        )
        == "POS_CLOSE_SHIFT 999"
    )
    assert _unsupported_definition_subject(
        "Claim that every BOT workflow completes without any network access.", evidence
    )


def test_explicit_unknown_population_is_rejected_before_retrieval() -> None:
    request = RagRequest(
        projectId="T2.0",
        collectionName="project-intelligence",
        textField="chunk_text",
        embeddingField="embedding_text",
        embeddingModel="multilingual-e5-large",
        schemaVersion="3",
        question="List every QZ phantom event defined by the project.",
        accessPolicyIds=["project:T2.0"],
        modelProfile="budget",
    )

    response = clarification_response(request, ("BOT", "POS", "IOT"))

    assert response is not None
    assert response.status == "INSUFFICIENT_EVIDENCE"
    assert response.failure_reason == "EXPLICIT_UNSUPPORTED_PREMISE"
    assert response.refusal_reason == "POPULATION_RETRIEVAL_MISS"


def test_overloaded_work_item_noun_requires_supporting_intent() -> None:
    assert _source_route_intent("How do I print a ticket?") == "CODE_ASSISTED"
    assert _source_route_intent("How do I reprint a receipt ticket?") == "CODE_ASSISTED"
    assert _source_route_intent("Show open tickets in the sprint") == "DELIVERY"
    assert _source_route_intent("What is the priority of issue APP-42?") == "DELIVERY"
    assert _source_route_intent("Give me APP-42 details") == "DELIVERY"


def test_device_visibility_language_gets_a_detection_retrieval_variant() -> None:
    assert (
        "detect"
        in retrieval_terminology_variant("BOT cannot see the Zebra after the count").casefold()
    )


def test_bare_overloaded_noun_fails_to_clarification_without_retrieval() -> None:
    response = clarification_response(
        RagRequest(
            projectId="DEMO",
            collectionName="knowledge",
            question="Give me the ticket details",
            accessPolicyIds=["project:DEMO"],
        ),
        (),
    )

    assert response is not None
    assert response.status == "NEEDS_CLARIFICATION"
    assert response.conversation_context_update is None


def test_translation_preserves_identifiers_numbers_quotes_and_entities() -> None:
    original = '¿Cómo funciona Atlas APP-42 versión 3 y "safe mode"?'
    assert _safe_translation_variant(
        original,
        'How does Atlas APP-42 version 3 and "safe mode" work?',
        ("atlas", "nova"),
    )
    assert not _safe_translation_variant(
        original,
        'How does Nova APP-42 version 3 and "safe mode" work?',
        ("atlas", "nova"),
    )


def test_noisy_variant_is_additive_and_never_rewrites_known_entity() -> None:
    corrected = corrected_query_variant("JOW KAN I LOK PRICE ON NOVA", ("atlas", "nova"))

    assert corrected
    assert "NOVA" in corrected
    assert corrected != "JOW KAN I LOK PRICE ON NOVA"
    assert corrected_query_variant("How can I check price on Nova?", ("atlas", "nova")) == ""
    assert retrieval_terminology_variant("How do I review a value?") == ("How do I check a value?")
    priority_variant = retrieval_terminology_variant("How do I filter priority?")
    assert "prioridad" in priority_variant
    assert "prioritarios" in priority_variant
    assert uncertain_entity_token("HOW DOES NAVA WORK?", ("nova", "atlas")) == "NAVA"
    assert uncertain_entity_token("HOW DOES NOVA WORK?", ("nova", "atlas")) == ""
    assert uncertain_entity_token("For project T2.0, explain this event", ("t0", "pos")) == ""
    assert uncertain_entity_token("What is the status of OPS-72?", ("opsx",)) == ""
    assert uncertain_entity_token("Explain release APP.2 and APP_ID", ("appx",)) == ""


def test_multilingual_rerank_keeps_max_qualifying_score_and_rrf() -> None:
    first = Document(page_content="one", metadata={"chunk_id": "one", "rerank_score": 0.7})
    second = Document(page_content="two", metadata={"chunk_id": "two", "rerank_score": 0.6})
    duplicate = Document(page_content="one", metadata={"chunk_id": "one", "rerank_score": 0.9})

    fused = _fuse_reranked_groups([[first, second], [duplicate]], top_n=2, rank_fusion_k=60)

    assert [item.metadata["chunk_id"] for item in fused] == ["one", "two"]
    assert fused[0].metadata["rerank_score"] == 0.9
