from __future__ import annotations

from typing import Any

from langgraph.errors import GraphRecursionError

from app.telemetry import stage_complete


async def invoke_bounded_graph(
    graph: Any, initial_state: dict[str, object], *, project_id: str,
    max_retrieval_attempts: int, began: float,
) -> dict[str, object]:
    """Run a workflow with enough headroom for every configured retry path."""

    recursion_limit = 12 + max_retrieval_attempts * 8
    try:
        return await graph.ainvoke(
            initial_state, config={"recursion_limit": recursion_limit}
        )
    except GraphRecursionError:
        stage_complete(
            "graph_error", project_id, began,
            reason_code="GRAPH_RECURSION_LIMIT",
            extra={"recursion_limit": recursion_limit},
        )
        raise
