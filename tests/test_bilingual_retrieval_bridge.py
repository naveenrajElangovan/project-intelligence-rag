"""Retrieval must bridge both language directions, not only Spanish to English.

The live failure this covers: an English question about Spanish-documented
material retrieved 40+ candidates, the cross-encoder scored the best of them at
0.009, and the pre-generation relevance gate refused before anything was
written. The user was told the details could not be confirmed, for a question
the corpus answers.
"""

import asyncio

from langchain_core.documents import Document

from app.config import Settings
from app.llm import BilingualQueryPlanner, TokenUsage
from app.models import RagRequest
from app.retrieval_pipeline import HeuristicContextEvaluator
from app.vocabulary import CorpusVocabulary
from app import workflow as workflow_module


ENGLISH_QUESTION = "Give me the flow for checking a price for leche"
SPANISH_QUESTION = "Dame el flujo para consultar un precio de leche"
SPANISH_VARIANT = "flujo de consulta de precio de leche"
ENGLISH_VARIANT = "price check flow for milk"


class RecordingPlanner:
    """A planner that records which direction the workflow asked for."""

    directions: list[str] = []

    def __init__(self, *_args) -> None:
        self.last_usage = TokenUsage()

    async def translate_to_english(self, question: str) -> str:
        RecordingPlanner.directions.append("to_english")
        return ENGLISH_VARIANT

    async def translate_to_spanish(self, question: str) -> str:
        RecordingPlanner.directions.append("to_spanish")
        return SPANISH_VARIANT

    async def plan(self, question: str):  # pragma: no cover - must not be reached
        raise AssertionError("Translation alone should satisfy this question.")


def _settings() -> Settings:
    # Expansion off so the only planner call under test is the translation one.
    return Settings(
        _env_file=None,
        environment="development",
        adaptive_query_enabled=False,
        query_expansion_enabled=False,
    )


def _planned(question: str) -> dict:
    RecordingPlanner.directions = []
    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question=question,
        accessPolicyIds=["project:DEMO"],
    )
    workflow = workflow_module.AuthorizedRagWorkflow.__new__(
        workflow_module.AuthorizedRagWorkflow
    )
    workflow._request = request
    workflow._settings = _settings()
    workflow._vocabulary = CorpusVocabulary(entities=("pos", "bot"))
    workflow._query_planner_factory = RecordingPlanner
    return asyncio.run(workflow._plan_queries({"request": request}))


def test_english_question_gains_a_spanish_retrieval_variant() -> None:
    """The direction that was missing entirely."""

    planned = _planned(ENGLISH_QUESTION)

    assert RecordingPlanner.directions == ["to_spanish"]
    assert any(SPANISH_VARIANT in query for query in planned["queries"])


def test_spanish_question_still_gains_an_english_variant() -> None:
    """The direction that already worked must keep working."""

    planned = _planned(SPANISH_QUESTION)

    assert RecordingPlanner.directions == ["to_english"]
    assert any(ENGLISH_VARIANT in query for query in planned["queries"])


def test_the_original_question_is_always_retrieved_too() -> None:
    for question in (ENGLISH_QUESTION, SPANISH_QUESTION):
        planned = _planned(question)
        assert any(question in query for query in planned["queries"])


def test_planner_offers_both_translation_directions() -> None:
    assert hasattr(BilingualQueryPlanner, "translate_to_english")
    assert hasattr(BilingualQueryPlanner, "translate_to_spanish")


def _document(score: float) -> Document:
    return Document(page_content="Consulta de precio.", metadata={"rerank_score": score})


def test_pre_generation_relevance_bar_is_configurable() -> None:
    """0.25 was a literal; the live refusal turned on evidence scoring 0.009."""

    evaluator = HeuristicContextEvaluator()
    documents = [_document(0.009)]

    strict = evaluator.evaluate("question", documents, relevance_threshold=0.25)
    assert strict.quality == "INSUFFICIENT"
    assert strict.failure_reason == "LOW_RELEVANCE"
    assert strict.retry_recommended is True

    permissive = evaluator.evaluate("question", documents, relevance_threshold=0.005)
    assert permissive.quality == "SUFFICIENT"
    assert permissive.failure_reason == ""


def test_relevance_bar_default_is_unchanged() -> None:
    assert Settings(_env_file=None, environment="development").context_relevance_threshold == 0.25
    evaluator = HeuristicContextEvaluator()
    assert evaluator.evaluate("q", [_document(0.24)]).quality == "INSUFFICIENT"
    assert evaluator.evaluate("q", [_document(0.26)]).quality == "SUFFICIENT"


def _router(attempt: int, documents: list[Document], missing: tuple[str, ...] = ("x",)):
    from app.workflow_nodes.retrieval import RetrievalNodesMixin

    router = RetrievalNodesMixin.__new__(RetrievalNodesMixin)
    router._settings = _settings()
    state = {
        "missing_requirements": missing,
        "retrieval_attempt": attempt,
        "documents": documents,
    }
    return router._route_after_evidence_completeness(state)


def test_exhausted_retries_still_attempt_an_answer_when_evidence_exists() -> None:
    """The refusal-without-trying bug: this used to route straight to 'end'."""

    settings = _settings()
    assert _router(settings.max_retrieval_attempts, [_document(0.009)]) == "generate"


def test_an_empty_evidence_pool_still_fails_closed() -> None:
    settings = _settings()
    assert _router(settings.max_retrieval_attempts, []) == "end"


def test_repair_is_still_preferred_while_retries_remain() -> None:
    assert _router(1, [_document(0.009)]) == "repair_completeness"


def test_complete_evidence_goes_straight_to_generation() -> None:
    assert _router(1, [_document(0.9)], missing=()) == "generate"


def test_an_ungrounded_request_still_ends() -> None:
    from app.workflow_nodes.retrieval import RetrievalNodesMixin

    router = RetrievalNodesMixin.__new__(RetrievalNodesMixin)
    router._settings = _settings()
    state = {"grounded": False, "missing_requirements": (), "documents": [_document(0.9)]}
    assert router._route_after_evidence_completeness(state) == "end"
