"""Executable boundaries that keep the RAG graph maintainable."""

from pathlib import Path


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
