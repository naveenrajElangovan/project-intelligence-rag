"""Retrieval must bridge both language directions, not only Spanish to English.

The live failure this covers: an English question about Spanish-documented
material retrieved 40+ candidates, the cross-encoder scored the best of them at
0.009, and the pre-generation relevance gate refused before anything was
written. The user was told the details could not be confirmed, for a question
the corpus answers.
"""

import asyncio

import pytest
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


def test_english_translation_preallocates_its_retrieval_slot() -> None:
    """Retrieval fills this stable index while the original query is in flight."""

    planned = _planned(ENGLISH_QUESTION)

    assert RecordingPlanner.directions == []
    assert planned["translation_slot"] == 1
    assert planned["queries"] == (ENGLISH_QUESTION, "")


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


def _router(
    attempt: int,
    documents: list[Document],
    missing: tuple[str, ...] = ("x",),
    relevance: float = 0.009,
):
    from app.workflow_nodes.retrieval import RetrievalNodesMixin

    router = RetrievalNodesMixin.__new__(RetrievalNodesMixin)
    router._settings = _settings()
    state = {
        "missing_requirements": missing,
        "retrieval_attempt": attempt,
        "documents": documents,
        "context_relevance": relevance,
    }
    return router._route_after_evidence_completeness(state)


def test_exhausted_retries_still_attempt_an_answer_when_evidence_exists() -> None:
    """The refusal-without-trying bug: this used to route straight to 'end'."""

    settings = _settings()
    assert _router(settings.max_retrieval_attempts, [_document(0.009)]) == "generate"


def test_exhausted_low_scored_evidence_still_reaches_truth_gates() -> None:
    settings = _settings()
    documents = [_document(0.0009)]

    assert _router(
        settings.max_retrieval_attempts, documents, relevance=0.0009
    ) == "generate"
    assert _router(
        settings.max_retrieval_attempts, documents, relevance=0.0011
    ) == "generate"


@pytest.mark.parametrize("floor", (-0.1, 0.25, 0.5, 1.1))
def test_context_relevance_floor_must_be_bounded_below_repair_threshold(
    floor: float,
) -> None:
    with pytest.raises(ValueError, match="CONTEXT_RELEVANCE_FLOOR"):
        Settings(
            _env_file=None,
            environment="development",
            context_relevance_floor=floor,
        )


def test_an_empty_evidence_pool_still_fails_closed() -> None:
    settings = _settings()
    assert _router(settings.max_retrieval_attempts, []) == "end"


def test_repair_is_still_preferred_while_retries_remain() -> None:
    assert _router(1, [_document(0.009)]) == "repair_completeness"


def test_complete_evidence_goes_straight_to_generation() -> None:
    assert _router(1, [_document(0.9)], missing=()) == "generate"


def test_explicit_zero_relevance_with_evidence_reaches_truth_gates() -> None:
    from app.workflow_nodes.retrieval import RetrievalNodesMixin

    router = RetrievalNodesMixin.__new__(RetrievalNodesMixin)
    router._settings = _settings()
    assert router._route_after_evidence_completeness(
        {
            "documents": [_document(0.0)],
            "context_quality": "INSUFFICIENT",
            "context_relevance": 0.0,
            "missing_requirements": (),
            "retrieval_attempt": 1,
        }
    ) == "generate"


def test_a_populated_ungrounded_request_still_reaches_the_truth_gate() -> None:
    from app.workflow_nodes.retrieval import RetrievalNodesMixin

    router = RetrievalNodesMixin.__new__(RetrievalNodesMixin)
    router._settings = _settings()
    state = {"grounded": False, "missing_requirements": (), "documents": [_document(0.9)]}
    assert router._route_after_evidence_completeness(state) == "generate"


def test_context_quality_prose_does_not_become_a_repair_requirement() -> None:
    from app.workflow_nodes.retrieval import RetrievalNodesMixin

    request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="Explain the checkout flow",
        accessPolicyIds=["project:DEMO"],
    )
    workflow = RetrievalNodesMixin.__new__(RetrievalNodesMixin)
    workflow._request = request
    workflow._settings = _settings()
    workflow._vocabulary = CorpusVocabulary()
    result = asyncio.run(
        workflow._validate_evidence_completeness(
            {
                "documents": [_document(0.01)],
                "retrieval_attempt": 1,
                "language": "en",
            }
        )
    )

    assert result["missing_requirements"] == ()
    assert result["context_failure_reason"] == "LOW_RELEVANCE"
