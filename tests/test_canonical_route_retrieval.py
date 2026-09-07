from langchain_core.documents import Document

from app.workflow_nodes.retrieval import _canonical_route_tokens


def _index(content: str, path: str = "[QUESTION-ORDER] Efficient order") -> Document:
    return Document(page_content=content, metadata={"structure_path": [path]})


def test_exact_canonical_question_exposes_approved_section_routes() -> None:
    document = _index(
        'Equivalent questions: "How do I filter by priority?" '
        "Routes: [ORDER-CATEGORIES], [ORDER-STOCK], [QUESTION-OTHER]."
    )

    assert _canonical_route_tokens("How do I filter by priority?", [document]) == (
        "ORDER-CATEGORIES",
        "ORDER-STOCK",
    )


def test_index_route_requires_full_question_and_question_structure() -> None:
    content = 'Equivalent questions: "How do I filter by priority?" [ORDER-CATEGORIES].'

    assert _canonical_route_tokens("How do I filter?", [_index(content)]) == ()
    assert _canonical_route_tokens(
        "How do I filter by priority?", [_index(content, "[GUIDE] Filters")]
    ) == ()


def test_short_question_does_not_trigger_index_route_expansion() -> None:
    assert _canonical_route_tokens(
        "Priority?", [_index("Priority? [ORDER-CATEGORIES]")]
    ) == ()
