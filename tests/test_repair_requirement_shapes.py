"""An unprefixed requirement must not fail the request.

Observed in production: `requirement.split(":", 1)[1]` raised IndexError inside
the rerank node, which LangGraph re-raised through the stream, and the request
ended FAILED / INDEXERROR with no answer at all.
"""

from langchain_core.documents import Document

from app.workflow_support.completeness import _include_repair_evidence


def _documents() -> list[Document]:
    return [
        Document(page_content="Shift closure is confirmed by the terminal.",
                 metadata={"chunk_id": "a", "title": "Workflows"}),
        Document(page_content="An unrelated passage about printers.",
                 metadata={"chunk_id": "b", "title": "Hardware"}),
    ]


def test_a_requirement_without_a_kind_prefix_does_not_raise() -> None:
    ranked = _include_repair_evidence(
        [], _documents(), ("closure",), top_n=4
    )
    assert isinstance(ranked, list)


def test_a_prefixed_requirement_still_matches_on_its_term() -> None:
    ranked = _include_repair_evidence(
        [], _documents(), ("identifier:closure",), top_n=4
    )
    assert isinstance(ranked, list)


def test_an_empty_requirement_tuple_is_a_no_op() -> None:
    ranked = _documents()
    assert _include_repair_evidence(ranked, ranked, (), top_n=4) == ranked


def test_a_bare_colon_requirement_does_not_raise() -> None:
    assert isinstance(
        _include_repair_evidence([], _documents(), (":",), top_n=4), list
    )
