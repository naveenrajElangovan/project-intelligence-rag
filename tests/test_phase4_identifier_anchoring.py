from langchain_core.documents import Document

from app.workflow_nodes.answering import _expand_standalone_identifier_question
from app.workflow_nodes.retrieval import (
    _exact_identifier_tokens,
    _forced_anchor_tokens,
    _inventory_identifier_anchors,
    _prefilter_candidates,
    _preserve_identifier_anchors,
    _retain_explicit_identifier_anchors,
)
from app.workflow_support.query_analysis import _exact_terms


def test_exact_terms_recognizes_digit_free_screaming_snake_identifier() -> None:
    terms = _exact_terms("what are the fields of ORDER_CREATED_EVENT")

    assert "order_created_event" in terms
    assert {"order", "created", "event"}.issubset(terms)


def test_identifier_extraction_is_dynamic_and_ignores_generic_acronyms() -> None:
    assert _exact_identifier_tokens("Show POS_LOGIN through the API") == ("POS_LOGIN",)
    assert _exact_identifier_tokens("What is LOGIN_POS_EVENT?") == ("LOGIN_POS_EVENT",)


def test_exact_lookup_includes_family_versions_and_explicit_strings() -> None:
    assert _exact_identifier_tokens(
        "Give me all 1xx events from `v0.4` and \"settlement family\""
    ) == ("1xx", "v0.4", "settlement family")
    assert _forced_anchor_tokens(
        'Compare LOGIN_POS_EVENT, 1xx, and "settlement family"'
    ) == ("1xx", "settlement family")


def test_prefilter_keeps_exact_anchors_and_drops_low_dense_zero_overlap() -> None:
    low_noise = Document(
        page_content="unrelated",
        metadata={"chunk_id": "noise", "score": 0.1, "exact_term_ratio": 0.0},
    )
    anchor = Document(
        page_content="1xx",
        metadata={
            "chunk_id": "anchor",
            "score": 0.0,
            "exact_term_ratio": 0.0,
            "identifier_anchor": True,
        },
    )
    responsive = Document(
        page_content="events",
        metadata={"chunk_id": "responsive", "score": 0.9, "exact_term_ratio": 0.5},
    )

    high_signal = [
        Document(
            page_content=f"event {index}",
            metadata={
                "chunk_id": f"signal-{index}",
                "score": 0.8,
                "exact_term_ratio": 0.5,
            },
        )
        for index in range(5)
    ]
    kept, reasons = _prefilter_candidates(
        [low_noise, anchor, responsive, *high_signal]
    )

    assert kept == [anchor, responsive, *high_signal]
    assert reasons["zero_overlap_low_dense"] == 1


def test_identifier_anchors_survive_the_final_evidence_limit() -> None:
    anchor = Document(
        page_content='@SerialName("POS_LOGIN") data class LoginEvent',
        metadata={"chunk_id": "anchor", "identifier_anchor": True, "identifier_anchor_score": 100},
    )
    ranked = [Document(page_content="summary", metadata={"chunk_id": "summary", "rerank_score": 0.9})]

    result = _preserve_identifier_anchors(ranked, [anchor, *ranked], top_n=2)

    assert result == [anchor, ranked[0]]
    assert anchor.metadata["rerank_score"] == 1.0


def test_inventory_exact_anchor_delivery_is_page_only_and_score_ordered() -> None:
    low_page = Document(
        page_content="POS family (1xx)",
        metadata={
            "identifier_anchor": True,
            "identifier_anchor_score": 20,
            "source_type": "PAGE",
        },
    )
    high_page = Document(
        page_content="POS registry (1xx)",
        metadata={
            "identifier_anchor": True,
            "identifier_anchor_score": 40,
            "source_type": "PAGE",
        },
    )
    code = Document(
        page_content="const val FAMILY = 1xx",
        metadata={
            "identifier_anchor": True,
            "identifier_anchor_score": 100,
            "source_type": "CODE",
        },
    )

    result = _inventory_identifier_anchors(
        [low_page, code, high_page], top_n=2
    )

    assert result == [high_page, low_page]
    assert all(document.metadata["rerank_score"] == 1.0 for document in result)


def test_rare_term_matches_do_not_become_forced_identifier_anchors() -> None:
    explicit = Document(
        page_content="POS family (1xx)",
        metadata={"identifier_anchor": True, "identifier_anchor_score": 40},
    )
    rare = Document(
        page_content="unusual replenishment wording",
        metadata={"identifier_anchor": True, "identifier_anchor_score": 2},
    )

    result = _retain_explicit_identifier_anchors([explicit, rare], ("1xx",))

    assert result[0].metadata["identifier_anchor"] is True
    assert "identifier_anchor" not in result[1].metadata
    assert result[1].metadata["rare_term_match"] is True


def test_standalone_identifier_requests_the_complete_contract() -> None:
    anchored = Document(page_content="payload", metadata={"identifier_anchor": True})

    expanded = _expand_standalone_identifier_question("POS_LOGIN", [anchored])

    assert "complete contract details" in expanded
    assert "every declared payload field" in expanded


def test_member_detail_question_requests_the_same_complete_contract() -> None:
    anchored = Document(page_content="payload", metadata={"identifier_anchor": True})

    bare = _expand_standalone_identifier_question("POS_LOGIN", [anchored])
    phrased = _expand_standalone_identifier_question(
        "what are the event details we need for POS_LOGIN", [anchored]
    )

    assert phrased == bare
