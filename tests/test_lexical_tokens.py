"""The lexical channel must see inside compound identifiers.

Before this, `POS_CLOSE_SHIFT_EVENT` was one atomic term. A Confluence page that
spells the same event `POS_CLOSE_SHIFT` shared none of it, so the most
discriminating word in the question scored nothing and BM25 ranked unrelated
prose -- which repeats "event", "what", "require" -- above the page that defines
the event. Measured on the real corpus, the defining section moved from rank 108
to rank 21 of 224 once identifiers were split.
"""

from langchain_core.documents import Document

from app.lexical_tokens import subtokens, tokens
from app.retrieval_pipeline import BM25Retriever


def test_snake_case_identifier_yields_its_parts():
    assert tokens("POS_CLOSE_SHIFT_EVENT") == [
        "pos_close_shift_event",
        "pos",
        "close",
        "shift",
        "event",
    ]


def test_camel_case_identifier_yields_its_parts():
    assert subtokens("shiftSummary") == ["shift", "summary"]
    assert subtokens("CloseShiftEvent") == ["close", "shift", "event"]


def test_acronym_boundary_splits_correctly():
    assert subtokens("POSEventHandler") == ["pos", "event", "handler"]


def test_digit_bearing_identifier_keeps_its_alpha_parts():
    assert subtokens("api3bRequestsTimeout") == ["api3b", "requests", "timeout"]


def test_path_yields_segments():
    assert subtokens("app/workflow_nodes/retrieval.py") == [
        "app",
        "workflow",
        "nodes",
        "retrieval",
        "py",
    ]


def test_plain_word_is_not_duplicated():
    # Re-emitting a one-part token would double its term frequency and distort BM25.
    assert tokens("event") == ["event"]
    assert subtokens("event") == []


def test_version_number_contributes_no_lonely_digits():
    assert tokens("0.4") == ["0.4"]
    assert subtokens("104") == []


def test_single_character_parts_are_dropped():
    assert subtokens("a_bc") == []
    assert subtokens("ab_cd") == ["ab", "cd"]


def test_constant_query_now_matches_the_wire_name_page():
    defining = Document(
        page_content="### `POS_CLOSE_SHIFT` - id 104. Payload class `CloseShiftEvent`.",
        metadata={"title": "Event contract"},
    )
    unrelated = Document(
        page_content="This event requires what the operator does; the event flow is described here.",
        metadata={"title": "Workflows"},
    )
    ranked = BM25Retriever().rank(
        "POS_CLOSE_SHIFT_EVENT what does this event require?", [unrelated, defining]
    )
    assert ranked[0].metadata["title"] == "Event contract"
    assert ranked[0].metadata["lexical_score"] > ranked[1].metadata["lexical_score"]


def test_query_and_documents_use_the_same_tokenizer():
    # Asymmetric tokenisation would corrupt BM25's term statistics.
    from app.retrieval_pipeline import _tokens

    assert _tokens("shiftSummary") == tokens("shiftSummary")
