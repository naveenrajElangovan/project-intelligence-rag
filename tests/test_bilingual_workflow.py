import asyncio
from pathlib import Path

from langchain_core.documents import Document

from app.config import Settings
from app.llm import (
    GroundedAnswer,
    GroundingVerdict,
    QueryPlan,
    TokenUsage,
    _documents_for_answer_style,
)
from app.models import RagRequest
from app.reranking import LocalMultilingualReranker
from app.vocabulary import CorpusVocabulary
from app import workflow as workflow_module
from app.workflow_nodes.retrieval import _final_evidence_order
from app.workflow_support.inventory_intent import is_inventory_question
from app.workflow_support import completeness as completeness_module


class FakeRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def ainvoke(self, query: str) -> list[Document]:
        self.queries.append(query)
        if query.startswith("¿"):
            return [_document("es-1", "spec", "La autorización usa el proyecto DEMO.", "es", 0.91)]
        return [
            _document("en-1", "code", "Authorization is enforced for project DEMO.", "en", 0.89),
            _document("es-1", "spec", "La autorización usa el proyecto DEMO.", "es", 0.80),
        ]

    def drain_usage(self) -> dict[str, int]:
        return {"embedding_tokens": 0, "read_units": 0, "retry_count": 0}

    def corpus_vocabulary(self) -> CorpusVocabulary:
        return CorpusVocabulary(
            entities=("pos", "bot"), code_extensions=(".kt", ".kts")
        )


class EmptyRetriever(FakeRetriever):
    async def ainvoke(self, query: str) -> list[Document]:
        self.queries.append(query)
        return []


class FakePlanner:
    def __init__(self, *args) -> None:
        self.last_usage = TokenUsage()
        self.model_name = "fake-planner"

    async def plan(self, question: str) -> QueryPlan:
        return QueryPlan(language="es", translated_query="How is authorization applied to DEMO?")


class DirectEnglishPlanner(FakePlanner):
    async def plan(self, question: str) -> QueryPlan:
        return QueryPlan(
            language="en",
            translated_query="How many files are in POS Payment?",
            search_queries=["POS Payment implementation footprint"],
            reason_code="DIRECT",
        )


class MultiPartEnglishPlanner(FakePlanner):
    async def plan(self, question: str) -> QueryPlan:
        return QueryPlan(
            language="en",
            search_queries=[
                "How is POS authorization implemented?",
                "How is POS authorization documented?",
            ],
            reason_code="MULTI_PART",
        )


class MixedSpanishPlanner(FakePlanner):
    async def plan(self, question: str) -> QueryPlan:
        return QueryPlan(
            language="mixed",
            translated_query="What is the POS payment process?",
            reason_code="DIRECT",
        )


class FakeReranker:
    def __init__(self, *args) -> None:
        self.last_retry_count = 0

    async def rerank(self, query: str, documents: list[Document]) -> list[Document]:
        for index, document in enumerate(documents):
            document.metadata["rerank_score"] = 0.9 - index / 10
        return documents


class FakeGenerator:
    def __init__(self, *args) -> None:
        self.last_usage = TokenUsage()
        self.model_name = "fake-generator"

    async def answer(self, question, documents, language) -> GroundedAnswer:
        assert language == "es"
        return GroundedAnswer(
            answer="La autorización se limita al proyecto DEMO [SOURCE 1].",
            citations=[1],
            missing_information=[],
        )

    async def repair(self, *args) -> GroundedAnswer:
        raise AssertionError("Citation repair should not run for a valid answer.")

    async def verify(self, *args, **kwargs) -> GroundingVerdict:
        return GroundingVerdict(supported=True, reason_code="SUPPORTED")


class FakeGroundingVerifier:
    def __init__(self, *args) -> None:
        self.last_usage = TokenUsage()
        self.model_name = "fake-grounding"

    async def verify(self, *args, **kwargs) -> GroundingVerdict:
        return GroundingVerdict(supported=True, reason_code="SUPPORTED")

    async def attach_missing_citations(self, documents, answer) -> GroundedAnswer:
        return answer


class FakeSafeResponseGenerator:
    def __init__(self, *args) -> None:
        self.last_usage = TokenUsage(input_tokens=10, output_tokens=9)
        self.model_name = "fake-safe-responder"

    async def generate(self, question, language, reason) -> str:
        assert question == "¿Cuál es la política lunar del proyecto?"
        assert language == "es"
        assert reason == "INSUFFICIENT_EVIDENCE"
        return "No tengo información indexada suficiente para responder eso; prueba con una pregunta más específica."


def _document(chunk_id: str, source_id: str, text: str, language: str, score: float) -> Document:
    return Document(
        page_content=text,
        metadata={
            "chunk_id": chunk_id,
            "source_id": source_id,
            "score": score,
            "source_type": "DOCUMENT",
            "title": source_id,
            "reference": source_id,
            "language": language,
            "locator": "page:1",
        },
    )


def test_graph_searches_original_and_translation_and_returns_only_cited_sources(monkeypatch) -> None:
    retriever = FakeRetriever()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "BilingualQueryPlanner", FakePlanner)
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="¿Cómo se aplica la autorización a DEMO?",
        accessPolicyIds=["project:DEMO", "project:OTHER"],
    )

    response = asyncio.run(
        workflow_module.AuthorizedRagWorkflow(
            Settings(_env_file=None, environment="development"), request
        ).run()
    )

    assert set(retriever.queries) == {
        "¿Cómo se aplica la autorización a DEMO?",
        "How is authorization applied to DEMO?",
    }
    assert response.answer.startswith("La autorización")
    assert [source.reference for source in response.sources] == ["spec"]
    assert response.sources[0].language == "es"


def test_direct_english_plan_does_not_multiply_retrieval_queries(monkeypatch) -> None:
    retriever = FakeRetriever()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "BilingualQueryPlanner", DirectEnglishPlanner)
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="How many files are in POS Payment?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )

    planned = asyncio.run(workflow._plan_queries({"request": request}))

    assert planned["queries"] == (request.question,)


def test_multi_part_english_question_is_decomposed_before_retrieval(monkeypatch) -> None:
    monkeypatch.setattr(workflow_module, "BilingualQueryPlanner", MultiPartEnglishPlanner)
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: FakeRetriever()),
    )
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question=(
            "How is POS authorization implemented, and how is it documented, "
            "and what differs between them?"
        ),
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )

    planned = asyncio.run(workflow._plan_queries({"request": request}))

    assert planned["queries"] == (
        request.question,
        "How is POS authorization implemented?",
        "How is POS authorization documented?",
    )


def test_spanish_answer_language_and_original_terms_are_preserved_for_reranking(
    monkeypatch,
) -> None:
    retriever = FakeRetriever()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "BilingualQueryPlanner", MixedSpanishPlanner)
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="¿Cuál es el proceso de pago en POS?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )

    planned = asyncio.run(workflow._plan_queries({"request": request}))

    assert planned["language"] == "es"
    assert planned["queries"] == (
        request.question,
        "What is the POS payment process?",
    )
    assert planned["rerank_query"] == request.question


def test_no_evidence_uses_model_written_safe_response_without_sources(monkeypatch) -> None:
    retriever = EmptyRetriever()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "BilingualQueryPlanner", FakePlanner)
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(
        workflow_module, "LangChainSafeResponseGenerator", FakeSafeResponseGenerator
    )
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="¿Cuál es la política lunar del proyecto?",
        accessPolicyIds=["project:DEMO"],
    )

    response = asyncio.run(
        workflow_module.AuthorizedRagWorkflow(
            Settings(_env_file=None, environment="development"), request
        ).run()
    )

    assert response.confidence == "NONE"
    assert response.sources == []
    assert response.answer.startswith("No tengo información indexada suficiente")


def test_entity_overview_intent_is_bounded_to_broad_pos_or_bot_questions() -> None:
    entities = ("pos", "bot")
    assert workflow_module._entity_overview_entity("Tell me about POS", entities) == "pos"
    assert workflow_module._entity_overview_entity("Tell me POS", entities) == "pos"
    assert workflow_module._entity_overview_entity("POS", entities) == "pos"
    assert workflow_module._entity_overview_entity("What is BOT?", entities) == "bot"
    assert workflow_module._entity_overview_entity("¿Qué es POS?", entities) == "pos"
    assert workflow_module._entity_overview_entity("Háblame de BOT", entities) == "bot"
    assert workflow_module._entity_overview_entity("Cuéntame sobre la aplicación POS", entities) == "pos"
    assert workflow_module._entity_overview_entity("¿Qué sabes de BOT?", entities) == "bot"
    assert workflow_module._entity_overview_entity("Tell me about POS Shift", entities) == ""
    assert workflow_module._entity_overview_entity("Tell me about the POS now", entities) == "pos"
    assert workflow_module._entity_overview_entity(
        "Hello good evening, what do you know about the POS application?", entities
    ) == "pos"
    assert workflow_module._entity_overview_entity("Compare POS and BOT", entities) == ""
    assert workflow_module._entity_overview_entity("Tell me about POS") == ""
    assert workflow_module.detect_query_language("Tell me about POS") == "en"


def test_code_location_queries_request_concept_expansion() -> None:
    assert workflow_module._code_location_query(
        "which code is having aaos home functionality"
    )
    assert workflow_module._code_location_query(
        "where is the main screen implemented"
    )
    assert not workflow_module._code_location_query("what is the project status")


def test_complete_question_with_that_does_not_inherit_previous_subject() -> None:
    assert not workflow_module._conversation_resolution_needed(
        "what is cluster that you know?"
    )
    assert workflow_module._conversation_resolution_needed("what is it?")


def test_feature_inventory_intent_requires_entity_features_and_exhaustive_wording() -> None:
    assert workflow_module._feature_inventory_entity(
        "List me all feature we have in POS", ("pos", "bot")
    ) == "pos"
    assert workflow_module._feature_inventory_entity(
        "Enumera todas las funcionalidades de BOT", ("pos", "bot")
    ) == "bot"
    assert workflow_module._feature_inventory_entity("Tell me about POS") == ""
    assert workflow_module._feature_inventory_entity("List all project features") == ""


def test_feature_inventory_keeps_only_unique_entity_feature_pages() -> None:
    payment = _document("payment-1", "payment", "Payment details", "en", 0.9)
    payment.metadata["title"] = "POS-Payment-Documentation"
    payment.metadata.update(entity="pos", doc_category="feature-page")
    duplicate = _document("payment-2", "payment-copy", "More payment details", "en", 0.8)
    duplicate.metadata["title"] = "pos payment documentation"
    duplicate.metadata.update(entity="pos", doc_category="feature-page")
    hub = _document("hub", "hub", "POS and BOT feature library", "en", 0.7)
    hub.metadata["title"] = "Documentation Library for EXAMPLE RETAIL: POS and BOT Features"
    bot = _document("bot", "bot", "BOT details", "en", 0.6)
    bot.metadata["title"] = "BOT-Login-Documentation"
    bot.metadata.update(entity="bot", doc_category="feature-page")

    inventory = workflow_module._inventory_documents(
        [payment, duplicate, hub, bot], "pos"
    )

    assert [document.metadata["title"] for document in inventory] == [
        "POS-Payment-Documentation"
    ]
    assert inventory[0].page_content == (
        "Indexed feature document title: POS-Payment-Documentation"
    )


def test_project_overview_intent_is_bounded_to_the_project_as_a_whole() -> None:
    assert workflow_module._project_overview_requested(
        "What do you know about DEMO project?", "DEMO"
    )
    assert workflow_module._project_overview_requested(
        "Tell me about this project", "DEMO"
    )
    assert workflow_module._project_overview_requested(
        "¿Qué sabes del proyecto DEMO?", "DEMO"
    )
    assert workflow_module._project_overview_requested(
        "Háblame de este proyecto", "DEMO"
    )
    assert workflow_module._project_overview_requested("¿Qué es DEMO?", "DEMO")
    assert not workflow_module._project_overview_requested(
        "What is the status of DEMO project?", "DEMO"
    )
    assert not workflow_module._project_overview_requested(
        "Tell me about POS Payment", "DEMO"
    )


def test_project_overview_removes_placeholders_and_balances_facets() -> None:
    placeholder = _document(
        "home", "home", "In a sentence or two, describe the purpose of this space.", "en", 0.9
    )
    placeholder.metadata["title"] = "DEMO"
    placeholder.metadata["low_information"] = True
    pos = _document("pos", "pos", "POS payment workflows.", "en", 0.8)
    pos.metadata["title"] = "POS-Payment-Documentation"
    pos.metadata["entity"] = "pos"
    bot = _document("bot", "bot", "BOT cash workflows.", "en", 0.7)
    bot.metadata["title"] = "BOT-Cash-Documentation"
    bot.metadata["entity"] = "bot"
    architecture = _document("arch", "arch", "Integration architecture.", "en", 0.6)
    architecture.metadata["title"] = "T20-Architecture"

    ordered = workflow_module._project_overview_evidence_order(
        [placeholder, pos, bot, architecture]
    )

    assert [document.metadata["chunk_id"] for document in ordered] == [
        "pos",
        "bot",
        "arch",
    ]


class ClaimFallbackVerifier(FakeGroundingVerifier):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def verify(
        self, question, documents, answer, *, answer_language=""
    ) -> GroundingVerdict:
        self.calls += 1
        unsupported = "An unsupported project claim is present [SOURCE 2]."
        if unsupported in answer.answer:
            return GroundingVerdict(
                supported=False,
                unsupported_claims=[unsupported],
                reason_code="UNSUPPORTED_CLAIM",
            )
        return GroundingVerdict(supported=True, reason_code="SUPPORTED")


def test_project_overview_drops_only_rejected_claim_and_reverifies(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: FakeRetriever()),
    )
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="What do you know about DEMO project?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )
    verifier = ClaimFallbackVerifier()
    workflow._grounding_verifier = verifier
    documents = [
        _document("one", "one", "First evidence.", "en", 0.9),
        _document("two", "two", "Second evidence.", "en", 0.8),
        _document("three", "three", "Third evidence.", "en", 0.7),
    ]
    generated = GroundedAnswer(
        answer=(
            "The first supported project claim is present [SOURCE 1]. "
            "An unsupported project claim is present [SOURCE 2]. "
            "The second supported project claim is present [SOURCE 3]."
        ),
        citations=[1, 2, 3],
    )

    result = asyncio.run(
        workflow._verify_grounding(
            {
                "documents": documents,
                "generated": generated,
                "query_intent": "PROJECT_OVERVIEW",
                "language": "en",
            }
        )
    )

    assert result["grounded"] is True
    assert result["grounding_reason"] == "CLAIMS_REMOVED_SUPPORTED"
    assert "unsupported project claim" not in result["generated"].answer
    assert result["generated"].citations == [1, 3]
    assert verifier.calls == 2


def test_thin_pruned_answer_regenerates_once_from_remaining_evidence(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: FakeRetriever()),
    )
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Tell me about the project",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development", answer_detail="detailed"),
        request,
    )
    verifier = ClaimFallbackVerifier()
    workflow._grounding_verifier = verifier

    class Regenerator:
        def __init__(self):
            self.calls = 0
            self.last_usage = TokenUsage()

        async def answer(self, *args, **kwargs):
            self.calls += 1
            return GroundedAnswer(
                answer=" ".join(
                    f"Supported regenerated detail number {index} [SOURCE {1 if index % 2 else 3}]."
                    for index in range(1, 7)
                ),
                citations=[1, 3],
            )

    generator = Regenerator()
    workflow._generator = generator
    documents = [
        _document("one", "one", "First evidence.", "en", 0.9),
        _document("two", "two", "Second evidence.", "en", 0.8),
        _document("three", "three", "Third evidence.", "en", 0.7),
    ]
    generated = GroundedAnswer(
        answer=(
            "The first supported project claim is present [SOURCE 1]. "
            "An unsupported project claim is present [SOURCE 2]. "
            "The second supported project claim is present [SOURCE 3]."
        ),
        citations=[1, 2, 3],
    )

    result = asyncio.run(
        workflow._verify_grounding(
            {
                "documents": documents,
                "generated": generated,
                "answer_style": "entity_overview",
                "query_intent": "DIRECT",
                "language": "en",
            }
        )
    )

    assert result["grounded"] is True
    assert result["grounding_reason"] == "AFTER_PRUNE_REGENERATED_SUPPORTED"
    assert workflow_module._material_sentence_count(result["generated"].answer) == 6
    assert generator.calls == 1
    assert verifier.calls == 3


def test_claim_fallback_does_not_release_a_single_remaining_claim() -> None:
    answer = GroundedAnswer(
        answer=(
            "A supported statement remains [SOURCE 1]. "
            "An unsupported statement is removed [SOURCE 2]."
        ),
        citations=[1, 2],
    )

    pruned, removed = workflow_module._remove_unsupported_claims(
        answer, ["An unsupported statement is removed [SOURCE 2]."]
    )

    assert removed == 1
    assert workflow_module._material_sentence_count(pruned.answer) == 1


def test_visible_answer_hides_markers_without_changing_sentence_text() -> None:
    visible = workflow_module._answer_without_source_markers(
        "BOT handles tools [SOURCE 7]. Login is documented [SOURCE 3] [SOURCE 8]. "
        "Several features are documented [SOURCE 1], [SOURCE 2], [SOURCE 3]."
    )

    assert visible == (
        "BOT handles tools. Login is documented. Several features are documented."
    )


class ProjectOverviewRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def ainvoke(self, query: str) -> list[Document]:
        self.queries.append(query)
        placeholder = _document(
            "home", "home", "This list below will automatically update each time somebody in your space creates or updates content.", "en", 0.95
        )
        placeholder.metadata.update({"title": "DEMO", "provider": "CONFLUENCE", "source_type": "PAGE", "low_information": True})
        pos = _document("pos", "pos", "POS covers payment workflows.", "en", 0.85)
        pos.metadata.update({"title": "POS-Payment-Documentation", "provider": "CONFLUENCE", "source_type": "PAGE", "entity": "pos"})
        bot = _document("bot", "bot", "BOT covers cash workflows.", "en", 0.84)
        bot.metadata.update({"title": "BOT-Cash-Documentation", "provider": "CONFLUENCE", "source_type": "PAGE", "entity": "bot"})
        architecture = _document("arch", "arch", "DEMO uses event routing integrations.", "en", 0.83)
        architecture.metadata.update({"title": "T20-Architecture", "provider": "CONFLUENCE", "source_type": "PAGE"})
        return [placeholder, pos, bot, architecture]

    def drain_usage(self) -> dict[str, int]:
        return {"embedding_tokens": 0, "read_units": 0, "retry_count": 0}

    def corpus_vocabulary(self) -> CorpusVocabulary:
        return CorpusVocabulary(entities=("pos", "bot"))


class ProjectOverviewReranker(FakeReranker):
    def __init__(self) -> None:
        super().__init__()
        self.queries: list[str] = []
        self.thresholds: list[float | None] = []

    async def rerank(self, query, documents, *, score_threshold=None):
        self.queries.append(query)
        self.thresholds.append(score_threshold)
        return await super().rerank(query, documents)


class ProjectOverviewGenerator(FakeGenerator):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.answer_style = ""

    async def answer(self, question, documents, language, *, answer_style="concise"):
        self.answer_style = answer_style
        assert all("automatically update" not in document.page_content for document in documents)
        return GroundedAnswer(
            answer=(
                "DEMO evidence covers POS payment workflows [SOURCE 1]. "
                "It also covers BOT cash workflows [SOURCE 2]. "
                "The architecture evidence describes event-routing integrations [SOURCE 3]."
            ),
            citations=[1, 2, 3],
        )

    async def repair(
        self, question, documents, language, invalid, *, answer_style="concise"
    ):
        self.answer_style = answer_style
        return invalid


def test_project_overview_uses_focused_rerank_and_project_answer_style(monkeypatch) -> None:
    retriever = ProjectOverviewRetriever()
    reranker = ProjectOverviewReranker()
    generator = ProjectOverviewGenerator()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: reranker)
    monkeypatch.setattr(
        workflow_module, "LangChainGroundedAnswerGenerator", lambda *args: generator
    )
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="What do you know about DEMO project?",
        accessPolicyIds=["project:DEMO"],
    )

    response = asyncio.run(
        workflow_module.AuthorizedRagWorkflow(
            Settings(_env_file=None, environment="development"), request
        ).run()
    )

    assert retriever.queries == [
        request.question,
        "DEMO pos application overview features workflows architecture",
        "DEMO bot application overview features workflows architecture",
    ]
    assert reranker.queries == [
        "pos application overview features workflows architecture",
        "bot application overview features workflows architecture",
        "DEMO architecture integrations platform",
    ]
    assert reranker.thresholds == [0.05, 0.05, 0.05]
    assert generator.answer_style == "project_overview"
    assert "POS payment workflows" in response.answer
    assert "[SOURCE" not in response.answer
    assert {source.reference for source in response.sources} == {"pos", "bot", "arch"}


def test_entity_overview_title_scope_excludes_the_other_product() -> None:
    pos = _document("pos", "pos-source", "POS facts", "en", 0.8)
    pos.metadata["title"] = "POS-Shift-Documentation"
    pos.metadata["entity"] = "pos"
    bot = _document("bot", "bot-source", "BOT facts", "en", 0.9)
    bot.metadata["title"] = "BOT-Cash-Documentation"
    bot.metadata["entity"] = "bot"
    unrelated = _document("other", "other-source", "Other facts", "en", 0.99)
    unrelated.metadata["title"] = "Architecture Documentation"

    assert workflow_module._entity_overview_source_ids("pos", [pos, bot, unrelated]) == {
        "pos-source"
    }


class EntityOverviewRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def ainvoke(self, query: str) -> list[Document]:
        self.queries.append(query)
        pos_shift = _document(
            "pos-shift", "pos-shift", "POS Shift manages store shift workflows.", "en", 0.82
        )
        pos_shift.metadata["title"] = "POS-Shift-Documentation"
        pos_shift.metadata["entity"] = "pos"
        pos_payment = _document(
            "pos-payment", "pos-payment", "POS Payment covers payment workflows.", "en", 0.79
        )
        pos_payment.metadata["title"] = "POS-Payment-Documentation"
        pos_payment.metadata["entity"] = "pos"
        bot_cash = _document(
            "bot-cash", "bot-cash", "BOT Cash covers cash workflows.", "en", 0.95
        )
        bot_cash.metadata["title"] = "BOT-Cash-Documentation"
        bot_cash.metadata["entity"] = "bot"
        return [bot_cash, pos_shift, pos_payment]

    def drain_usage(self) -> dict[str, int]:
        return {"embedding_tokens": 0, "read_units": 0, "retry_count": 0}

    def corpus_vocabulary(self) -> CorpusVocabulary:
        return CorpusVocabulary(entities=("pos", "bot"))


class EntityOverviewReranker(FakeReranker):
    def __init__(self) -> None:
        super().__init__()
        self.query = ""
        self.threshold = None

    async def rerank(self, query, documents, *, score_threshold=None):
        self.query = query
        self.threshold = score_threshold
        return await super().rerank(query, documents)


class EntityOverviewGenerator(FakeGenerator):
    def __init__(self, *args) -> None:
        super().__init__(*args)
        self.answer_style = ""

    async def answer(self, question, documents, language, *, answer_style="concise"):
        self.answer_style = answer_style
        assert all(document.metadata["title"].startswith("POS-") for document in documents)
        return GroundedAnswer(
            answer=(
                "In DEMO, POS covers store-facing operational workflows [SOURCE 1].\n\n"
                "The indexed evidence includes shift and payment capabilities [SOURCE 1] [SOURCE 2]."
            ),
            citations=[1, 2],
        )


def test_entity_overview_uses_bounded_queries_scoped_reranking_and_conversational_answer(
    monkeypatch,
) -> None:
    retriever = EntityOverviewRetriever()
    reranker = EntityOverviewReranker()
    generator = EntityOverviewGenerator()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: reranker)
    monkeypatch.setattr(
        workflow_module, "LangChainGroundedAnswerGenerator", lambda *args: generator
    )
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Tell me about POS",
        accessPolicyIds=["project:DEMO"],
    )

    response = asyncio.run(
        workflow_module.AuthorizedRagWorkflow(
            Settings(_env_file=None, environment="development"), request
        ).run()
    )

    assert retriever.queries == [
        "Tell me about POS",
        "POS application overview",
        "POS features workflows architecture",
    ]
    assert reranker.query == "POS application overview features workflows architecture"
    assert reranker.threshold == 0.05
    assert generator.answer_style == "entity_overview"
    assert "shift and payment capabilities" in response.answer
    assert {source.reference for source in response.sources} == {"pos-shift", "pos-payment"}


def test_final_evidence_order_preserves_enumeration_depth_and_diversifies_other_queries() -> None:
    first_a = _document("a1", "a", "first a", "en", 0.9)
    second_a = _document("a2", "a", "second a", "en", 0.8)
    third_a = _document("a3", "a", "third a", "en", 0.75)
    first_b = _document("b1", "b", "first b", "en", 0.7)
    first_c = _document("c1", "c", "first c", "en", 0.6)
    first_d = _document("d1", "d", "first d", "en", 0.5)

    ranked = [first_a, second_a, third_a, first_b, first_c, first_d]
    enumeration = _final_evidence_order(
        ranked,
        top_n=4,
        enumeration=is_inventory_question("can you give me all POS shortcuts?"),
    )
    non_enumeration = _final_evidence_order(
        ranked,
        top_n=4,
        enumeration=is_inventory_question("how does a POS shift close?"),
    )

    assert [document.metadata["chunk_id"] for document in enumeration] == [
        "a1",
        "a2",
        "a3",
        "b1",
    ]
    assert [document.metadata["chunk_id"] for document in non_enumeration] == [
        "a1",
        "b1",
        "c1",
        "d1",
    ]


def test_entity_overview_style_repair_detects_only_unsolicited_metrics() -> None:
    assert workflow_module._overview_style_repair_needed(
        "Tell me POS",
        "POS Payment has 35 files [SOURCE 1].",
    )
    assert not workflow_module._overview_style_repair_needed(
        "How many files are in POS Payment?",
        "POS Payment has 35 files [SOURCE 1].",
    )
    assert not workflow_module._overview_style_repair_needed(
        "Tell me POS",
        "POS includes payment and shift workflows [SOURCE 1].",
    )


def test_entity_overview_rejects_symbol_inventory_as_an_answer() -> None:
    answer = (
        "The POS About Application is implemented by the following files and symbols: "
        "com.example.pos.AboutRoute, com.example.pos.AboutViewModel, "
        "and com.example.pos.AboutState [SOURCE 1]."
    )

    assert workflow_module._overview_style_repair_needed(
        "Tell me about the POS now", answer
    )


def test_entity_overview_generation_context_removes_metrics_but_keeps_capabilities() -> None:
    document = _document(
        "pos",
        "pos",
        "Cash count results are verified.\n35 source files\nUI: 15 symbols\nLifecycle status: Draft\nAbout has 262 source lines",
        "en",
        0.9,
    )

    filtered = _documents_for_answer_style([document], "entity_overview")[0].page_content

    assert "Cash count results are verified." in filtered
    assert "35 source files" not in filtered
    assert "15 symbols" not in filtered
    assert "Lifecycle status" not in filtered
    assert "262 source lines" not in filtered

    table_document = _document(
        "table",
        "table",
        "Layer | Symbols | Responsibility\nUI | 31 | Compose rendering\nHandles replenishment requests.",
        "en",
        0.8,
    )
    filtered_table = _documents_for_answer_style(
        [table_document], "entity_overview"
    )[0].page_content
    assert "UI | 31" not in filtered_table
    assert "Handles replenishment requests." in filtered_table


class FakeLocalReranker(LocalMultilingualReranker):
    def __init__(self, *, top_n: int, score_threshold: float, max_chunks_per_source: int):
        super().__init__(
            "fake", device="cpu", model_path="", revision="test", top_n=top_n,
            score_threshold=score_threshold, exact_code_score_threshold=1.0,
            exact_code_retrieval_score_floor=1.0,
            max_chunks_per_source=max_chunks_per_source,
        )

    def _predict(self, query, documents):
        return [0.9, 0.8, 0.7][:len(documents)]


def test_reranker_limits_chunks_per_source() -> None:
    documents = [
        _document("1", "same", "first", "en", 0.9),
        _document("2", "same", "second", "es", 0.8),
        _document("3", "different", "third", "en", 0.7),
    ]
    reranker = FakeLocalReranker(top_n=8, score_threshold=0.35, max_chunks_per_source=1)

    result = asyncio.run(reranker.rerank("authorization", documents))

    assert [document.metadata["source_id"] for document in result] == ["same", "different"]


def test_source_cap_cannot_empty_non_empty_scored_documents() -> None:
    documents = [
        _document("1", "same", "first", "en", 0.9),
        _document("2", "same", "second", "en", 0.8),
    ]
    reranker = FakeLocalReranker(
        top_n=8, score_threshold=0.35, max_chunks_per_source=1
    )

    result = asyncio.run(reranker.rerank("authorization", documents))

    assert result
    assert reranker.last_source_cap_bypassed is False


def test_reranker_does_not_evict_ranked_evidence_for_visual_metadata() -> None:
    documents = [
        _document("1", "text-a", "first", "en", 0.9),
        _document("2", "text-b", "second", "en", 0.8),
        _document("3", "visual", "diagram", "en", 0.7),
    ]
    documents[2].metadata["visual_asset_ids"] = ["opaque"]
    reranker = FakeLocalReranker(top_n=2, score_threshold=0.35, max_chunks_per_source=1)

    result = asyncio.run(reranker.rerank("architecture diagram", documents))

    assert len(result) == 2
    assert [document.metadata["source_id"] for document in result] == ["text-a", "text-b"]


def test_reranker_can_expand_only_for_an_explicit_exhaustive_intent() -> None:
    documents = [
        _document("1", "a", "first", "en", 0.9),
        _document("2", "b", "second", "en", 0.8),
        _document("3", "c", "third", "en", 0.7),
    ]
    reranker = FakeLocalReranker(top_n=2, score_threshold=0.0, max_chunks_per_source=1)

    result = asyncio.run(reranker.rerank("all POS features", documents, top_n=3))

    assert len(result) == 3


def test_invalid_citations_are_rejected() -> None:
    invalid = GroundedAnswer(answer="Claim [SOURCE 2].", citations=[2])
    assert workflow_module._citations_valid(invalid, 1) is False


def test_exact_feature_title_affinity_rejects_related_subfeature() -> None:
    exact = _document("shift", "shift", "Shift facts", "en", 0.8)
    exact.metadata["title"] = "POS-Shift-Documentation"
    exact.metadata["entity"] = "pos"
    related = _document("funding", "funding", "Funding facts", "en", 0.99)
    related.metadata["title"] = "POS-Shift-Funding-Documentation"
    related.metadata["entity"] = "pos"

    assert workflow_module._exact_feature_title_match("What is listed for POS Shift?", exact)
    assert not workflow_module._exact_feature_title_match(
        "What is listed for POS Shift?", related
    )
    assert workflow_module._exact_feature_title_match(
        "What is listed for POS Shift Funding?", exact
    )
    assert workflow_module._exact_feature_title_match(
        "What is listed for POS Shift Funding?", related
    )
    assert workflow_module._exact_feature_source_ids(
        "What is listed for POS Shift Funding?", [exact, related]
    ) == {"funding"}


def test_completeness_detects_missing_count_and_enumerated_category() -> None:
    footprint = "How many Kotlin source files and nonblank Kotlin lines were observed in POS Shift?"
    screens = "Which close, open, and loading screen types are listed for POS Shift?"

    assert workflow_module._missing_answer_requirements(
        footprint, "27 Kotlin source files were observed [SOURCE 1]."
    ) == ("count:lines",)
    assert workflow_module._missing_answer_requirements(
        screens, "CloseShiftScreen and ShiftLoadingScreen are listed [SOURCE 1]."
    ) == ("term:open",)


def test_completeness_repair_tolerates_and_logs_colonless_requirement_once(
    monkeypatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(
        completeness_module.LOGGER, "warning", lambda message: warnings.append(message)
    )

    query = workflow_module._completeness_repair_query(
        "What POS behavior is missing?",
        [],
        ("unscoped+requirement", "unscoped+requirement"),
    )

    assert query == "unscoped requirement unscoped requirement"
    assert len(warnings) == 1
    assert '"reason_code":"MALFORMED_REQUIREMENT"' in warnings[0]
    assert '"value":"unscoped+requirement"' in warnings[0]


def test_explicit_code_request_rejects_imports_and_symbol_lists() -> None:
    question = "Show me the complete implementation code for closing a shift"
    assert workflow_module._code_output_requested(question)
    assert not workflow_module._code_answer_complete(
        question,
        "```kotlin\nimport app.shift.CloseShift\nimport app.shift.Repository\n```",
    )
    assert not workflow_module._code_answer_complete(
        question,
        "CloseShiftUseCase, ShiftRepository, and closeShift.",
    )
    assert workflow_module._code_answer_complete(
        question,
        "```kotlin\nclass CloseShiftUseCase {\n    fun execute() { repository.close() }\n}\n```",
    )
    assert workflow_module._missing_answer_requirements(
        question, "The relevant symbols are CloseShiftUseCase and closeShift."
    ) == ("code:implementation",)


def test_behavior_question_does_not_require_or_force_source_code() -> None:
    question = "What does POS do?"
    assert not workflow_module._code_output_requested(question)
    assert workflow_module._missing_answer_requirements(
        question, "POS supports checkout and shift workflows [SOURCE 1]."
    ) == ()


def test_function_inventory_request_does_not_require_full_source_code() -> None:
    question = "Give me the important functions that make us login"
    assert not workflow_module._code_output_requested(question)
    assert workflow_module._missing_answer_requirements(
        question,
        "`authenticateUser` validates credentials and `refreshSession` renews the session [SOURCE 1].",
    ) == ()


def test_completeness_extracts_requested_ui_identifiers() -> None:
    question = (
        "Which BOT Cash UI types are listed for the cash screen, cash recollection ViewModel, "
        "and record-expenses screen?"
    )
    requirements = workflow_module._answer_requirements(question)
    documents = [
        _document(
            "cash-1",
            "cash",
            "CashScreen and CashRecollectionViewModel are listed.",
            "en",
            0.9,
        )
    ]

    assert requirements == (
        "identifier:cash+screen",
        "identifier:cash+recollection+viewmodel",
        "identifier:record+expense+screen",
    )
    assert workflow_module._missing_evidence_requirements(requirements, documents) == (
        "identifier:record+expense+screen",
    )
    assert workflow_module._missing_answer_requirements(
        question,
        "CashScreen, CashRecollectionViewModel, and RecordExpensesScreen are listed [SOURCE 1].",
    ) == ()

    documents[0].page_content += " RecordExpensesScreen and CashScreenContent are listed."
    exact = workflow_module._deterministic_identifier_answer(question, documents, "en")
    assert exact is not None
    assert exact.answer == (
        "The requested types are CashScreen, CashRecollectionViewModel, and "
        "RecordExpensesScreen [SOURCE 1]."
    )
    assert workflow_module._missing_answer_requirements(
        "Which three screen classes are listed for POS Shift close, open, and loading flows?",
        "CloseShiftScreen and ShiftLoadingScreen are listed [SOURCE 1].",
        ("pos", "bot"),
    ) == ("term:open",)


class ShiftRetriever:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def ainvoke(self, query: str) -> list[Document]:
        self.queries.append(query)
        close_and_loading = _document(
            "shift-1",
            "shift",
            "CloseShiftScreen and ShiftLoadingScreen are listed.",
            "en",
            0.8,
        )
        close_and_loading.metadata.update(
            {"title": "POS-Shift-Documentation", "source_type": "PAGE", "entity": "pos"}
        )
        funding = _document(
            "funding-1",
            "funding",
            "CloseShiftScreenContent is listed for funding.",
            "en",
            0.99,
        )
        funding.metadata.update(
            {"title": "POS-Shift-Funding-Documentation", "source_type": "PAGE", "entity": "pos"}
        )
        if query.casefold().startswith("pos shift") and "open" in query.casefold():
            open_screen = _document(
                "shift-2",
                "shift",
                "OpenShiftScreen is listed.",
                "en",
                0.85,
            )
            open_screen.metadata.update(
                {"title": "POS-Shift-Documentation", "source_type": "PAGE", "entity": "pos"}
            )
            return [open_screen]
        return [funding, close_and_loading]

    def drain_usage(self) -> dict[str, int]:
        return {"embedding_tokens": 0, "read_units": 0, "retry_count": 0}

    def corpus_vocabulary(self) -> CorpusVocabulary:
        return CorpusVocabulary(entities=("pos", "bot"), code_extensions=(".kt",))


class ShiftPlanner(FakePlanner):
    async def plan(self, question: str) -> QueryPlan:
        return QueryPlan(language="en", reason_code="DIRECT")


class ShiftGenerator(FakeGenerator):
    async def answer(self, question, documents, language) -> GroundedAnswer:
        has_open = any("OpenShiftScreen" in document.page_content for document in documents)
        answer = (
            "CloseShiftScreen, OpenShiftScreen, and ShiftLoadingScreen are listed [SOURCE 1]."
            if has_open
            else "CloseShiftScreen and ShiftLoadingScreen are listed [SOURCE 1]."
        )
        return GroundedAnswer(answer=answer, citations=[1])


class ShiftLimitingReranker(FakeReranker):
    async def rerank(self, query: str, documents: list[Document]) -> list[Document]:
        ranked = await super().rerank(query, documents)
        return ranked[:1]


def test_graph_performs_one_bounded_completeness_retrieval_repair(monkeypatch) -> None:
    retriever = ShiftRetriever()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "BilingualQueryPlanner", ShiftPlanner)
    monkeypatch.setattr(
        workflow_module, "build_reranker", lambda settings: ShiftLimitingReranker()
    )
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", ShiftGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    question = "Which three screen classes are listed for POS Shift close, open, and loading flows?"
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:DEMO"],
    )

    response = asyncio.run(
        workflow_module.AuthorizedRagWorkflow(
            Settings(_env_file=None, environment="development"), request
        ).run()
    )

    assert retriever.queries == [question, "POS shift open"]
    assert "OpenShiftScreen" in response.answer
    assert [source.reference for source in response.sources] == ["shift"]


def test_source_authority_intents_route_to_the_approved_provider() -> None:
    cases = {
        "How is login implemented?": (
            "IMPLEMENTATION",
            (("PAGE", "CODE"), "CONFLUENCE_GITHUB"),
        ),
        "What does POS do?": (
            "CODE_ASSISTED",
            (("PAGE", "CODE"), "CONFLUENCE_GITHUB"),
        ),
        "How is the invoice total calculated?": (
            "CODE_ASSISTED",
            (("PAGE", "CODE"), "CONFLUENCE_GITHUB"),
        ),
        "What is the delivery status in Jira?": ("DELIVERY", (("ISSUE",), "JIRA")),
        "Does the documented login flow match the implementation?": (
            "CROSS_SOURCE",
            (("PAGE", "CODE"), "CONFLUENCE_GITHUB"),
        ),
        "¿Cómo está implementado el inicio de sesión?": (
            "IMPLEMENTATION",
            (("PAGE", "CODE"), "CONFLUENCE_GITHUB"),
        ),
    }

    for question, (intent, scope) in cases.items():
        assert workflow_module._source_route_intent(question) == intent
        assert workflow_module._intent_source_scope(intent) == scope


def test_single_jira_status_uses_deterministic_fast_path(monkeypatch) -> None:
    class DeliveryRetriever(FakeRetriever):
        async def ainvoke_scoped(self, query, source_types=()):
            assert source_types == ("ISSUE",)
            document = _document(
                "issue-1",
                "T2-1",
                "Implementation of RAG delivery issue.",
                "en",
                0.88,
            )
            document.metadata.update(
                {
                    "source_type": "ISSUE",
                    "title": "Implementation of RAG",
                    "reference": "T2-1",
                    "status": "To Do",
                    "priority": "Medium",
                }
            )
            return [document]

    class UnexpectedReranker(FakeReranker):
        async def rerank(self, query, documents, **kwargs):
            raise AssertionError("A single Jira result must not be reranked.")

    retriever = DeliveryRetriever()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: UnexpectedReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Summarize project status",
        accessPolicyIds=["project:DEMO"],
    )

    response = asyncio.run(
        workflow_module.AuthorizedRagWorkflow(
            Settings(_env_file=None, environment="development"), request
        ).run()
    )

    assert response.answer == (
        "The status of 'Implementation of RAG' is 'To Do' with medium priority."
    )
    assert response.sources[0].reference == "T2-1"


def test_single_jira_details_tolerates_one_character_identifier_typo() -> None:
    document = _document(
        "issue-1",
        "T0-1",
        "Implementation of RAG - T20-0001",
        "en",
        0.88,
    )
    document.metadata.update(
        {
            "source_type": "ISSUE",
            "title": "Implementation of RAG - T20-0001",
            "issue_key": "T0-1",
            "reference": "T0-1",
            "issue_type": "Story",
            "status": "To Do",
            "priority": "Medium",
        }
    )

    answer = workflow_module._deterministic_delivery_answer(
        "What is the Jira details for T20-00001", [document], "en"
    )

    assert answer is not None
    assert answer.citations == [1]
    assert "identifier 'T20-0001'" in answer.answer
    assert "request 'T20-00001'" in answer.answer
    assert "Jira issue 'T0-1'" in answer.answer
    assert "Story" in answer.answer
    assert "status 'To Do'" in answer.answer
    assert "medium priority" in answer.answer


def test_single_jira_details_rejects_unrelated_identifier() -> None:
    document = _document(
        "issue-1",
        "T0-1",
        "Implementation of RAG - T20-0001",
        "en",
        0.88,
    )
    document.metadata.update(
        {
            "source_type": "ISSUE",
            "title": "Implementation of RAG - T20-0001",
            "issue_key": "T0-1",
            "reference": "T0-1",
            "status": "To Do",
        }
    )

    answer = workflow_module._deterministic_delivery_answer(
        "Show Jira details for XYZ-9999", [document], "en"
    )

    assert answer is None


def test_natural_file_questions_extract_matching_paths_from_any_authorized_source() -> None:
    shift = _document(
        "shift-1",
        "shift-doc",
        (
            "CloseShiftState.kt defines the close-shift state. "
            "ShiftLoadingScreen.kt renders loading."
        ),
        "en",
        0.9,
    )
    shift.metadata.update(
        {"source_type": "PAGE", "title": "POS-Shift-Documentation"}
    )
    invoice = _document(
        "invoice-1",
        "invoice-code",
        "CalculateInvoiceTotalUseCase.kt calculates the invoice total.",
        "en",
        0.9,
    )
    invoice.metadata.update({"source_type": "CODE", "path": "src/CalculateInvoiceTotalUseCase.kt"})

    shift_answer = workflow_module._deterministic_code_location_answer(
        "which file in POS has the close shift", [shift], "en", (".kt",)
    )
    invoice_answer = workflow_module._deterministic_code_location_answer(
        "what file implements invoice total calculation", [invoice], "en", (".kt",)
    )

    assert shift_answer is not None
    assert "`CloseShiftState.kt`" in shift_answer.answer
    assert shift_answer.citations == [1]
    assert invoice_answer is not None
    assert "`src/CalculateInvoiceTotalUseCase.kt`" in invoice_answer.answer
    assert invoice_answer.citations == [1]

    aaos = _document(
        "aaos-1",
        "aaos-home",
        "AaoSHome.kt contains the AAOS home screen entry point.",
        "en",
        0.9,
    )
    aaos.metadata.update({"source_type": "CODE", "path": "aaos/home/AaoSHome.kt"})
    aaos_answer = workflow_module._deterministic_code_location_answer(
        "ok which code is having aaos home and main", [aaos], "en", (".kt",)
    )

    assert aaos_answer is not None
    assert "`aaos/home/AaoSHome.kt`" in aaos_answer.answer


def test_general_code_question_keeps_relevant_source_file_ahead_of_readme(
    monkeypatch,
) -> None:
    def code_document(chunk_id: str, path: str, text: str) -> Document:
        document = _document(chunk_id, path, text, "en", 0.85)
        document.metadata.update(
            {
                "source_type": "CODE",
                "path": path,
                "title": path,
                "reference": path,
                "symbol": Path(path).stem,
            }
        )
        return document

    class CodeRetriever(FakeRetriever):
        async def ainvoke_scoped(self, query, source_types=()):
            assert source_types == ("PAGE", "CODE")
            return [
                code_document("readme-1", "README.md", "Application overview"),
                code_document("readme-2", "README.md", "Testing instructions"),
                code_document("factory", "InvoiceViewModelFactory.kt", "factory wiring"),
                code_document("module", "UseCaseModule.kt", "dependency injection wiring"),
                code_document(
                    "total",
                    "CalculateInvoiceTotalUseCase.kt",
                    "CalculateInvoiceTotalUseCase calculates and exposes the invoice total.",
                ),
            ]

    class WindowedCodeReranker:
        def __init__(self) -> None:
            self.last_retry_count = 0
            self.requested_top_n = 0

        async def rerank(
            self, query, documents, *, score_threshold=None, top_n=None
        ):
            self.requested_top_n = top_n or 2
            for index, document in enumerate(documents):
                document.metadata["rerank_score"] = 0.9 - index / 10
            return documents[: self.requested_top_n]

    retriever = CodeRetriever()
    reranker = WindowedCodeReranker()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: reranker)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Where in the source code is the invoice total calculated?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )

    planned = asyncio.run(workflow._plan_queries({"request": request}))
    retrieved = asyncio.run(workflow._retrieve(planned))
    ranked = asyncio.run(workflow._rerank({**planned, **retrieved}))

    assert planned["query_intent"] == "IMPLEMENTATION"
    assert planned["source_types"] == ("PAGE", "CODE")
    assert reranker.requested_top_n == 0
    assert [document.metadata["path"] for document in ranked["documents"]] == [
        "CalculateInvoiceTotalUseCase.kt",
        "InvoiceViewModelFactory.kt",
    ]
    assert all(document.metadata["path"] != "README.md" for document in ranked["documents"])


def test_exhaustive_code_inventory_is_bounded_deduplicated_and_metadata_verified() -> None:
    documents = []
    for index in range(30):
        document = _document(f"code-{index}", f"ref-{index}", "class content", "en", 0.9)
        document.metadata.update(
            {
                "source_type": "CODE",
                "repository": "naveenrajElangovan/aaos-compose-cluster",
                "branch": "main",
                "path": f"src/File{index}.kt",
                "symbol": f"File{index}",
            }
        )
        documents.extend((document, document))

    selected = workflow_module._code_inventory_documents(documents, 25)
    generated = workflow_module._deterministic_code_inventory_answer(selected, "en")

    assert workflow_module._code_inventory_requested("List all classes in POS") is True
    assert workflow_module._code_inventory_requested("List all POS features") is False
    assert len(selected) == 25
    assert generated is not None
    assert workflow_module._code_inventory_answer_verified(generated, selected) is True

    focused = workflow_module._code_inventory_documents(
        documents,
        25,
        "List all vehicle repository classes and functions in the indexed code",
    )
    assert focused == []


def test_conversation_resolution_uses_generic_subject_before_model(monkeypatch) -> None:
    class FakeConversationResolver:
        def __init__(self, *_args) -> None:
            self.last_usage = TokenUsage(input_tokens=20, output_tokens=8)

        async def resolve(self, question, history, language) -> str:
            raise AssertionError("A clear prior user subject must not need the model.")

    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: FakeRetriever()),
    )
    monkeypatch.setattr(
        workflow_module, "ConversationQueryResolver", FakeConversationResolver
    )
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="How is that implemented?",
        accessPolicyIds=["project:DEMO"],
        conversationHistory=[
            {"role": "user", "content": "Tell me about POS payment."},
            {"role": "assistant", "content": "POS payment handles payment workflows."},
        ],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )

    planned = asyncio.run(workflow._plan_queries({"request": request}))

    assert planned["resolved_question"] == (
        "How is that implemented? (previous subject: POS payment)"
    )
    assert planned["query_intent"] == "IMPLEMENTATION"
    assert planned["source_types"] == ("PAGE", "CODE")


def test_short_verb_ellipsis_uses_guarded_conversation_rewrite() -> None:
    class FakeConversationResolver:
        last_usage = TokenUsage(input_tokens=20, output_tokens=8)

        async def resolve(self, question, history, language) -> str:
            assert question == "I need for POS application"
            assert history
            return "What are the features of the POS application?"

    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="I need for POS application",
        accessPolicyIds=["project:DEMO"],
        conversationHistory=[
            {"role": "user", "content": "can you explain pos application features"},
            {"role": "assistant", "content": "POS application features are documented."},
            {"role": "user", "content": "can you explain what shortcuts it has"},
            {"role": "assistant", "content": "POS application shortcuts are documented."},
        ],
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(
        workflow_module.AuthorizedRagWorkflow
    )
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")
    workflow._conversation_resolver_factory = lambda *_args: FakeConversationResolver()

    resolved = asyncio.run(
        workflow._resolve_conversation_question(request.question, "en")
    )

    assert resolved == "What are the features of the POS application?"


def test_direct_conversation_question_does_not_need_resolution() -> None:
    assert workflow_module._conversation_resolution_needed("How is login implemented?") is False
    assert workflow_module._conversation_resolution_needed("How is that implemented?") is True
    assert workflow_module._conversation_resolution_needed("¿Cómo funciona eso?") is True
    assert workflow_module._conversation_resolution_needed("Continue") is True
    assert workflow_module._conversation_resolution_needed("What else?") is True
    assert workflow_module._conversation_resolution_needed("Anything more?") is True
    assert workflow_module._conversation_resolution_needed("And the prerequisites?") is True
    assert workflow_module._conversation_resolution_needed("Who is their owner?") is True


def test_followup_modifiers_are_not_misclassified_as_a_new_subject() -> None:
    assert workflow_module._conversation_subject("yes what it do specifically") == ""
    assert workflow_module._conversation_subject("okay, explain it further") == ""
    assert workflow_module._conversation_subject("sí, dime eso específicamente") == ""


def test_specific_followup_keeps_and_classifies_the_active_subject(monkeypatch) -> None:
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: FakeRetriever()),
    )
    monkeypatch.setattr(workflow_module, "build_reranker", lambda settings: FakeReranker())
    monkeypatch.setattr(workflow_module, "LangChainGroundedAnswerGenerator", FakeGenerator)
    monkeypatch.setattr(workflow_module, "LocalCitationGroundingVerifier", FakeGroundingVerifier)
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="yes what it do specifically",
        accessPolicyIds=["project:DEMO"],
        conversationContext={"activeSubject": "POS application", "stateRevision": 2},
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )

    planned = asyncio.run(workflow._plan_queries({"request": request}))

    assert planned["resolved_question"] == (
        "yes what it do specifically (previous subject: POS application)"
    )
    assert planned["query_intent"] == "ENTITY_OVERVIEW"
    assert planned["overview_entity"] == "pos"
    assert all("POS" in query for query in planned["queries"])


def test_existing_noisy_subject_is_cleaned_during_followup_resolution() -> None:
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="yes what it do specifically",
        accessPolicyIds=["project:DEMO"],
        conversationContext={
            "activeSubject": "hello good evening know POS application",
            "stateRevision": 3,
        },
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(
        workflow_module.AuthorizedRagWorkflow
    )
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")

    resolved = asyncio.run(workflow._resolve_conversation_question(request.question, "en"))
    update = workflow._conversation_context_update(
        {"resolved_question": resolved, "query_intent": "ENTITY_OVERVIEW"}
    )

    assert resolved.endswith("(previous subject: POS application)")
    assert update.active_subject == "POS application"


def test_followup_carries_generic_subject_from_previous_user_turn() -> None:
    history = [
        ("user", "detail of the Jira ticket T20-00001"),
        (
            "assistant",
            "Using T20-0001 for the request T20-00001, Jira issue 'T0-1' is To Do.",
        ),
    ]

    rewritten = workflow_module._deterministic_conversation_rewrite(
        "full detail about that?", history, "en"
    )

    assert rewritten == (
        "full detail about that? (previous subject: Jira ticket T20-00001)"
    )


def test_persisted_subject_resolves_followup_outside_transcript_window() -> None:
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Anything more?",
        accessPolicyIds=["project:DEMO"],
        conversationContext={
            "activeSubject": "customer payment reconciliation workflow",
            "stateRevision": 7,
        },
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(
        workflow_module.AuthorizedRagWorkflow
    )
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")

    resolved = asyncio.run(
        workflow._resolve_conversation_question(request.question, "en")
    )

    assert resolved == (
        "Anything more? (previous subject: customer payment reconciliation workflow)"
    )


def test_fresh_ambiguous_question_does_not_invent_conversation_state() -> None:
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="What about that?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(
        workflow_module.AuthorizedRagWorkflow
    )
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")

    resolved = asyncio.run(
        workflow._resolve_conversation_question(request.question, "en")
    )

    assert resolved == request.question


def test_explicit_new_subject_wins_over_previous_conversation_subject() -> None:
    question = "How does authentication work and where is it implemented?"
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:DEMO"],
        conversationContext={"activeSubject": "POS close shift"},
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(
        workflow_module.AuthorizedRagWorkflow
    )
    workflow._request = request
    workflow._settings = Settings(_env_file=None, environment="development")

    resolved = asyncio.run(workflow._resolve_conversation_question(question, "en"))

    assert resolved == question


def test_context_update_preserves_exact_resolved_subject() -> None:
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Anything more?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(
        workflow_module.AuthorizedRagWorkflow
    )
    workflow._request = request

    update = workflow._conversation_context_update(
        {
            "resolved_question": (
                "Anything more? (previous subject: POS close shift workflow)"
            ),
            "query_intent": "CODE_ASSISTED",
        }
    )

    assert update.active_subject == "POS close shift workflow"
    assert update.entities[0].canonical_value == "POS close shift workflow"
    assert update.intent == "CODE_ASSISTED"


def test_followup_subject_resolution_is_not_limited_to_entity_types() -> None:
    history = [
        ("user", "Explain the customer payment reconciliation workflow"),
        ("assistant", "It reconciles payment records."),
    ]

    rewritten = workflow_module._deterministic_conversation_rewrite(
        "What are its prerequisites?", history, "en"
    )

    assert rewritten == (
        "What are its prerequisites? "
        "(previous subject: customer payment reconciliation workflow)"
    )


def test_followup_skips_empty_chitchat_and_uses_earlier_meaningful_subject() -> None:
    history = [
        ("user", "Tell me about POS payment"),
        ("assistant", "POS payment handles payment workflows."),
        ("user", "more about that"),
        ("assistant", "Here are more details."),
    ]

    rewritten = workflow_module._deterministic_conversation_rewrite(
        "How does it work?", history, "en"
    )

    assert rewritten == "How does it work? (previous subject: POS payment)"


def test_verified_assistant_subject_survives_a_window_of_vague_user_followups() -> None:
    history = [
        ("user", "full detail about that?"),
        ("assistant", "Jira issue T0-1 is a Story with status To Do."),
        ("user", "anything more?"),
        ("assistant", "Here are the available details."),
    ]

    rewritten = workflow_module._deterministic_conversation_rewrite(
        "And its priority?", history, "en"
    )

    assert rewritten is not None
    assert "Jira issue T0-1 Story status" in rewritten


def test_conversation_subject_carryover_is_source_independent() -> None:
    cases = (
        (
            "Explain the POS payment workflow",
            "Go deeper",
            "CODE_ASSISTED",
        ),
        (
            "How is customer authentication implemented?",
            "What are its tests?",
            "IMPLEMENTATION",
        ),
        (
            "Describe the project architecture",
            "Continue",
            "CROSS_SOURCE",
        ),
        (
            "Show Jira issue T0-1",
            "What else?",
            "DELIVERY",
        ),
        (
            "Explain the cash reconciliation policy",
            "Give examples",
            "CODE_ASSISTED",
        ),
    )

    for previous_question, followup, expected_intent in cases:
        assert workflow_module._conversation_resolution_needed(followup) is True
        rewritten = workflow_module._deterministic_conversation_rewrite(
            followup, [("user", previous_question)], "en"
        )
        assert rewritten is not None
        assert workflow_module._source_route_intent(rewritten) == expected_intent


def test_unscoped_code_assisted_still_issues_a_dense_request(monkeypatch) -> None:
    """An unrestricted source scope means one dense query, never zero.

    The CODE_ASSISTED / CROSS_SOURCE fan-out builds one dense request per source
    type so a small family cannot be buried by a large one. With no scope at all
    that fan-out had nothing to iterate, so it produced an empty request list and
    the dense arm never executed: retrieval fell back to the lexical sample while
    still reporting `reason_code: OK`. The implementation-flow planner branch
    returns exactly this combination (query_intent CODE_ASSISTED, source_types ()),
    as does recovery after it widens a scope that returned nothing.
    """

    scopes_requested: list[tuple[str, ...]] = []

    class ScopeRecordingRetriever(FakeRetriever):
        async def ainvoke_scoped(self, query, source_types=()):
            scopes_requested.append(tuple(source_types))
            return [
                _document(
                    "login-1",
                    "code",
                    "The POS login screen submits credentials for project DEMO.",
                    "en",
                    0.88,
                )
            ]

    retriever = ScopeRecordingRetriever()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Tell me about the POS login and what happens after that",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )

    state = {
        "request": request,
        "queries": ("POS login flow",),
        "query_intent": "CODE_ASSISTED",
        "source_types": (),
        "source_route": "MIXED",
        "resolved_question": request.question,
    }
    retrieved = asyncio.run(workflow._retrieve(state))

    # One unrestricted request, not zero.
    assert scopes_requested == [()]
    # The bug was silent because the dense arm produced nothing while the stage
    # still reported success, so assert on the dense count rather than on the
    # merged candidate pool the lexical fallback also feeds.
    assert retrieved["dense_candidate_count"] == 1
    assert retrieved["candidates"]


def test_scoped_code_assisted_still_fans_out_per_source_type(monkeypatch) -> None:
    """The fan-out itself must survive the empty-scope fix."""

    scopes_requested: list[tuple[str, ...]] = []

    class ScopeRecordingRetriever(FakeRetriever):
        async def ainvoke_scoped(self, query, source_types=()):
            scopes_requested.append(tuple(source_types))
            return []

    retriever = ScopeRecordingRetriever()
    monkeypatch.setattr(
        workflow_module.ChromaAccessRetriever,
        "create",
        classmethod(lambda cls, **kwargs: retriever),
    )
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Where is the invoice total calculated?",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow(
        Settings(_env_file=None, environment="development"), request
    )

    state = {
        "request": request,
        "queries": ("invoice total",),
        "query_intent": "CODE_ASSISTED",
        "source_types": ("PAGE", "CODE"),
        "source_route": "CONFLUENCE_GITHUB",
        "resolved_question": request.question,
    }
    asyncio.run(workflow._retrieve(state))

    assert scopes_requested == [("PAGE",), ("CODE",)]
