import asyncio
from types import SimpleNamespace

from langchain_core.documents import Document

from app.workflow_nodes.answering import AnswerNodesMixin
from app.workflow_support.answer_structure import material_claims
from app.workflow_support.deterministic_answers import _deterministic_canonical_route_answer
from app.workflow_support.citations import _normalize_citations
from app.models import ConversationContext, RagRequest
from app.workflow_support.fail_closed import clarification_response_with_canonical_index
from app.workflow_nodes.retrieval import (
    _canonical_route_directive,
    _canonical_route_tokens,
    _is_canonical_route_control_document,
    _load_canonical_route_directive,
    _mark_structure_route_candidates,
    _matched_structure_route_tokens,
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
    assert (
        _canonical_route_tokens(
            "How do I filter by priority?", [_index(content, "[GUIDE] Filters")]
        )
        == ()
    )


def test_canonical_question_index_is_control_plane_not_answer_evidence() -> None:
    index = _index(
        'Preguntas equivalentes: "¿Cómo registro un gasto?" Rutas: [BOTOPS-EXPENSE].',
        "[QUESTION-CASH-OPS] Efectivo, alivios y gastos",
    )
    procedure = Document(
        page_content="Selecciona Registrar gastos y espera el folio.",
        metadata={"structure_path": ["[BOTOPS-EXPENSE] Registrar gastos"]},
    )

    assert _is_canonical_route_control_document(index)
    assert not _is_canonical_route_control_document(procedure)


def test_structure_route_coverage_does_not_count_body_only_index_mentions() -> None:
    index = _index(
        "Rutas: [BOTOPS-EXPENSE], [PRINT-EXPENSE].",
        "[QUESTION-CASH-OPS] Efectivo, alivios y gastos",
    )
    procedure = Document(
        page_content="Selecciona Registrar gastos y espera el folio.",
        metadata={
            "structure_path": ["[BOTOPS-EXPENSE] Registrar gastos"],
            "canonical_route_anchor": True,
        },
    )

    assert _matched_structure_route_tokens(
        [index, procedure], ("BOTOPS-EXPENSE", "PRINT-EXPENSE")
    ) == {"BOTOPS-EXPENSE"}


def test_semantic_target_beyond_structure_scan_cap_is_promoted() -> None:
    target = Document(
        page_content="Selecciona Registrar gastos y espera el folio.",
        metadata={"structure_path": ["[BOTOPS-EXPENSE] Registrar gastos"]},
    )
    unrelated = Document(
        page_content="Selecciona Fondo adicional.",
        metadata={"structure_path": ["[BOTOPS-ADDITIONAL-FUND] Fondo adicional"]},
    )

    _mark_structure_route_candidates([target, unrelated], ("BOTOPS-EXPENSE",))

    assert target.metadata["canonical_route_anchor"] is True
    assert target.metadata["canonical_route_match_score"] == 2.0
    assert "canonical_route_candidate" not in unrelated.metadata


def test_short_question_does_not_trigger_index_route_expansion() -> None:
    assert _canonical_route_tokens("Priority?", [_index("Priority? [ORDER-CATEGORIES]")]) == ()


def test_exact_two_word_question_uses_authorized_index_route() -> None:
    document = _index('Equivalent questions: "Restart service?" Route: [SERVICE-RESTART].')

    assert _canonical_route_tokens("Restart service?", [document]) == ("SERVICE-RESTART",)


def test_exact_corpus_declared_out_of_scope_question_returns_typed_directive() -> None:
    document = _index(
        'Equivalent questions: "How do I change configuration?" '
        "Route: [SUPPORT-OFF-TOPIC], [SUPPORT-NO-EVIDENCE].",
        "[QUESTION-OUT-OF-SCOPE] Unrelated or technical questions",
    )

    assert _canonical_route_directive("How do I change configuration?", [document]) == (
        ("SUPPORT-OFF-TOPIC", "SUPPORT-NO-EVIDENCE"),
        "INSUFFICIENT_EVIDENCE",
    )


def test_nearby_supported_configuration_question_is_not_keyword_refused() -> None:
    document = _index(
        'Equivalent questions: "How do I change configuration?" Route: [SUPPORT-OFF-TOPIC].',
        "[QUESTION-OUT-OF-SCOPE] Unrelated or technical questions",
    )

    assert _canonical_route_directive("Where is label-print configuration?", [document]) == ((), "")


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
    def __init__(self, index_document: Document | None) -> None:
        self.index_document = index_document
        self.canonical_source_types: tuple[str, ...] | None = None

    async def ainvoke(self, _query: str) -> list[Document]:
        return []

    async def ainvoke_scoped(self, _query: str, _source_types: tuple[str, ...]) -> list[Document]:
        return []

    async def ainvoke_canonical_questions(
        self, _question: str, _source_types: tuple[str, ...]
    ) -> list[Document]:
        self.canonical_source_types = _source_types
        return [self.index_document] if self.index_document is not None else []

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
    assert retriever.canonical_source_types == ()


def _request(question: str) -> RagRequest:
    return RagRequest(
        projectId="ANY-PROJECT",
        question=question,
        collectionName="project-intelligence",
        textField="chunk_text",
        embeddingField="embedding_text",
        embeddingModel="multilingual-e5-large",
        schemaVersion="3",
        accessPolicyIds=["project:ANY-PROJECT"],
        conversationContext=ConversationContext(),
    )


def test_exact_declared_fragment_bypasses_generic_followup_clarification() -> None:
    retriever = _CanonicalOnlyRetriever(
        _index('Equivalent questions: "It asks for a supervisor." Route: [AUTH-SUPERVISOR].')
    )

    assert (
        asyncio.run(
            clarification_response_with_canonical_index(
                _request("It asks for a supervisor."), (), ("PAGE",), retriever
            )
        )
        is None
    )


def test_unknown_fragment_keeps_generic_followup_clarification() -> None:
    response = asyncio.run(
        clarification_response_with_canonical_index(
            _request("It asks for a supervisor."), (), ("PAGE",), _CanonicalOnlyRetriever(None)
        )
    )
    assert response.failure_reason == ("AMBIGUOUS_FOLLOWUP")


def test_procedural_canonical_extract_keeps_two_source_claims() -> None:
    document = Document(
        page_content=(
            "Reconnect the Zebra once from the application screen. "
            "Wait for the visible connection before retrying the import. "
            "Do not change Linux permissions."
        ),
        metadata={"canonical_route_match": True, "source_type": "PAGE"},
    )

    answer = _deterministic_canonical_route_answer(
        "How do I reconnect the Zebra?", [document], "en"
    )

    assert answer is not None
    assert len(material_claims(answer.answer)) >= 2
    assert answer.citations == [1]


def test_exact_route_candidate_can_supply_a_complete_procedure_without_literal_overlap() -> None:
    document = Document(
        page_content=(
            "Select Operational tools from BOT. "
            "Wait until Loading Content disappears before continuing. "
            "Do not change the tool address."
        ),
        metadata={
            "canonical_route_candidate": True,
            "rerank_score": 0.8,
            "source_type": "PAGE",
        },
    )

    answer = _deterministic_canonical_route_answer(
        "The BOT tool stays blank; what should I do?", [document], "en"
    )

    assert answer is not None
    assert len(material_claims(answer.answer)) >= 2
    assert answer.citations == [1]


def test_route_candidate_alone_cannot_answer_a_nonprocedural_question() -> None:
    neighboring = Document(
        page_content=(
            "versionNumber = EventType.LOGIN_POS_EVENT.version. "
            "The session id is copied from the authentication result."
        ),
        metadata={
            "canonical_route_candidate": True,
            "rerank_score": 0.9,
            "source_type": "CODE",
        },
    )
    assert (
        _deterministic_canonical_route_answer(
            "Which event id and version does LOGIN_POS_EVENT have?", [neighboring], "en"
        )
        is None
    )


def test_exact_corpus_route_can_answer_a_terse_symptom_without_literal_overlap() -> None:
    routed_resolution = Document(
        page_content=(
            "Restart only the affected terminal. "
            "Verify that the sign-in screen is visible before retrying the sale."
        ),
        metadata={
            "canonical_route_candidate": True,
            "canonical_route_match": True,
            "canonical_route_match_score": 2.0,
            "source_type": "PAGE",
        },
    )

    answer = _deterministic_canonical_route_answer("Nothing works.", [routed_resolution], "en")

    assert answer is not None
    assert "Restart only the affected terminal" in answer.answer
    assert answer.citations == [1]


def test_exact_route_answer_prefers_the_requested_language() -> None:
    english = Document(
        page_content="Restart the affected terminal and verify the sign-in screen.",
        metadata={
            "canonical_route_match": True,
            "canonical_route_match_score": 2.0,
            "language": "en",
        },
    )
    spanish = Document(
        page_content="Reinicia la terminal afectada y verifica la pantalla de acceso.",
        metadata={
            "canonical_route_match": True,
            "canonical_route_match_score": 2.0,
            "language": "es",
        },
    )

    answer = _deterministic_canonical_route_answer("Nada funciona.", [english, spanish], "es")

    assert answer is not None
    assert "Reinicia la terminal" in answer.answer


def test_verified_canonical_extract_does_not_start_an_unrelated_completeness_repair() -> None:
    document = Document(
        page_content=(
            "Escanea el código una vez. Confirma la descripción y la cantidad antes de continuar."
        ),
        metadata={
            "canonical_route_match": True,
            "canonical_route_match_score": 2.0,
            "language": "es",
        },
    )
    question = "No lee el código."
    generated = _normalize_citations(
        _deterministic_canonical_route_answer(question, [document], "es")
    )
    node = AnswerNodesMixin.__new__(AnswerNodesMixin)
    node._request = SimpleNamespace(question=question, project_id="ANY-PROJECT")
    node._vocabulary = SimpleNamespace(entities=("codigo", "repository"))
    node._settings = SimpleNamespace(max_retrieval_attempts=2)

    result = asyncio.run(
        node._validate_completeness(
            {
                "resolved_question": question,
                "documents": [document],
                "generated": generated,
                "answer_style": "canonical_quote",
                "language": "es",
                "retrieval_attempt": 1,
            }
        )
    )

    assert result == {"missing_requirements": ()}


def test_canonical_title_phrase_beats_neighboring_shared_words() -> None:
    routed_parent = Document(
        page_content=(
            "## How to use this corpus\n"
            "Use the named source type when answering threshold questions. "
            "Cite the field that supplies the threshold.\n"
            "## Security\nSecret values are not included in this corpus."
        ),
        metadata={
            "canonical_route_match": True,
            "canonical_route_match_score": 2.0,
            "source_type": "PAGE",
        },
    )

    answer = _deterministic_canonical_route_answer(
        "Tell me about How to use this corpus.", [routed_parent], "en"
    )

    assert answer is not None
    assert "named source type" in answer.answer
    assert "Secret values" not in answer.answer
