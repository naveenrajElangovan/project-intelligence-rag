import asyncio
from types import SimpleNamespace

from langchain_core.documents import Document

from app.workflow_nodes.answering import AnswerNodesMixin
from app.workflow_nodes.retrieval import (
    _canonical_route_directive,
    _canonical_route_tokens,
    _load_canonical_route_directive,
)


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


def test_exact_corpus_declared_out_of_scope_question_returns_typed_directive() -> None:
    document = _index(
        'Equivalent questions: "How do I change configuration?" '
        "Route: [SUPPORT-OFF-TOPIC], [SUPPORT-NO-EVIDENCE].",
        "[QUESTION-OUT-OF-SCOPE] Unrelated or technical questions",
    )

    assert _canonical_route_directive(
        "How do I change configuration?", [document]
    ) == (
        ("SUPPORT-OFF-TOPIC", "SUPPORT-NO-EVIDENCE"),
        "INSUFFICIENT_EVIDENCE",
    )


def test_nearby_supported_configuration_question_is_not_keyword_refused() -> None:
    document = _index(
        'Equivalent questions: "How do I change configuration?" '
        "Route: [SUPPORT-OFF-TOPIC].",
        "[QUESTION-OUT-OF-SCOPE] Unrelated or technical questions",
    )

    assert _canonical_route_directive(
        "Where is label-print configuration?", [document]
    ) == ((), "")


def test_corpus_declared_disposition_skips_model_generation() -> None:
    node = AnswerNodesMixin.__new__(AnswerNodesMixin)
    node._request = SimpleNamespace(
        project_id="ANY-PROJECT", question="How do I change configuration?"
    )

    result = asyncio.run(
        node._generate(
            {
                "language": "en",
                "documents": [],
                "canonical_route_refusal_reason": "INSUFFICIENT_EVIDENCE",
            }
        )
    )

    assert result["generated"].outcome == "REFUSAL"
    assert result["generated_refusal_reason"] == "INSUFFICIENT_EVIDENCE"
    assert result["answer_style"] == "corpus_declared_refusal"


class _CanonicalOnlyRetriever:
    def __init__(self, index_document: Document) -> None:
        self.index_document = index_document

    async def ainvoke(self, _query: str) -> list[Document]:
        return []

    async def ainvoke_scoped(
        self, _query: str, _source_types: tuple[str, ...]
    ) -> list[Document]:
        return []

    async def ainvoke_canonical_questions(
        self, _question: str, _source_types: tuple[str, ...]
    ) -> list[Document]:
        return [self.index_document]

    def drain_usage(self) -> dict[str, int]:
        return {"embedding_tokens": 0, "retry_count": 0, "read_units": 0}


def test_canonical_disposition_does_not_depend_on_semantic_candidate_hit() -> None:
    retriever = _CanonicalOnlyRetriever(
        _index(
            'Equivalent questions: "\u00bfC\u00f3mo cambio la configuraci\u00f3n?" '
            "Route: [SUPPORT-OFF-TOPIC].",
            "[QUESTION-OUT-OF-SCOPE] Preguntas t\u00e9cnicas",
        )
    )
    result = asyncio.run(
        _load_canonical_route_directive(
            retriever,
            "\u00bfC\u00f3mo cambio la configuraci\u00f3n?",
            [],
            ("PAGE",),
        )
    )

    assert result == (("SUPPORT-OFF-TOPIC",), "INSUFFICIENT_EVIDENCE")
