import asyncio

from langchain_core.documents import Document

from app.models import RagRequest
from app.workflow_nodes.retrieval import _fuse_reranked_groups
from app.workflow_support.fail_closed import clarification_response
from app.workflow_support.query_analysis import (
    _safe_translation_variant,
    _source_route_intent,
    corrected_query_variant,
    retrieval_terminology_variant,
    uncertain_entity_token,
)


def test_overloaded_work_item_noun_requires_supporting_intent() -> None:
    assert _source_route_intent("How do I print a ticket?") == "CODE_ASSISTED"
    assert _source_route_intent("How do I reprint a receipt ticket?") == "CODE_ASSISTED"
    assert _source_route_intent("Show open tickets in the sprint") == "DELIVERY"
    assert _source_route_intent("What is the priority of issue APP-42?") == "DELIVERY"
    assert _source_route_intent("Give me APP-42 details") == "DELIVERY"


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
    corrected = corrected_query_variant(
        "JOW KAN I LOK PRICE ON NOVA", ("atlas", "nova")
    )

    assert corrected
    assert "NOVA" in corrected
    assert corrected != "JOW KAN I LOK PRICE ON NOVA"
    assert corrected_query_variant("How can I check price on Nova?", ("atlas", "nova")) == ""
    assert retrieval_terminology_variant("How do I review a value?") == (
        "How do I check a value?"
    )
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

    fused = _fuse_reranked_groups(
        [[first, second], [duplicate]], top_n=2, rank_fusion_k=60
    )

    assert [item.metadata["chunk_id"] for item in fused] == ["one", "two"]
    assert fused[0].metadata["rerank_score"] == 0.9
