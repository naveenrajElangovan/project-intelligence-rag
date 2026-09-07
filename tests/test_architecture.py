"""Executable boundaries that keep the RAG graph maintainable."""

from pathlib import Path

from langchain_core.documents import Document

from app.config import Settings
from app.workflow_nodes.answering import AnswerNodesMixin
from app.workflow_nodes.retrieval import RetrievalNodesMixin


APP = Path(__file__).parents[1] / "app"


def test_workflow_remains_a_small_composition_root() -> None:
    workflow = APP / "workflow.py"
    assert len(workflow.read_text().splitlines()) <= 450


def test_nodes_do_not_import_the_composition_root() -> None:
    for module in (APP / "workflow_nodes").glob("*.py"):
        assert "from app.workflow import" not in module.read_text()
        assert "import app.workflow" not in module.read_text()


def test_support_modules_do_not_depend_on_graph_nodes() -> None:
    for module in (APP / "workflow_support").glob("*.py"):
        assert "app.workflow_nodes" not in module.read_text()


def test_only_grounding_may_end_a_request_that_holds_documents() -> None:
    """Every pre-grounding router must preserve a populated evidence path."""

    document = Document(page_content="authorized evidence", metadata={})
    settings = Settings(_env_file=None, environment="development")

    retrieval = RetrievalNodesMixin.__new__(RetrievalNodesMixin)
    retrieval._settings = settings
    assert retrieval._route_after_rerank({"documents": [document]}) != "end"
    for grounded in (None, False):
        assert retrieval._route_after_evidence_completeness(
            {
                "documents": [document],
                "grounded": grounded,
                "missing_requirements": ("term:checkout",),
                "retrieval_attempt": settings.max_retrieval_attempts,
            }
        ) != "end"

    answering = AnswerNodesMixin.__new__(AnswerNodesMixin)
    answering._settings = settings
    for grounded in (None, False):
        assert answering._route_after_completeness(
            {
                "documents": [document],
                "grounded": grounded,
                "missing_requirements": ("term:checkout",),
                "retrieval_attempt": settings.max_retrieval_attempts,
            }
        ) == "verify_grounding"
