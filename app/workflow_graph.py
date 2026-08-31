from __future__ import annotations

from functools import lru_cache
from typing import Any, Awaitable, Callable

from langgraph.graph import END, START, StateGraph

from app.workflow_nodes.state import RagState


def _node(name: str) -> Callable[[RagState], Awaitable[RagState]]:
    async def invoke(state: RagState) -> RagState:
        return await getattr(state["_workflow"], name)(state)

    return invoke


def _route(name: str) -> Callable[[RagState], str]:
    return lambda state: str(getattr(state["_workflow"], name)(state))


@lru_cache(maxsize=1)
def compiled_workflow_graph() -> Any:
    """Compile the request-independent topology once for the whole process."""

    graph = StateGraph(RagState)
    for name in (
        "plan_queries", "retrieve", "feature_affinity", "rerank",
        "validate_evidence_completeness", "recover_query", "generate",
        "validate_citations", "validate_completeness", "repair_completeness",
        "verify_grounding",
    ):
        graph.add_node(name, _node(f"_{name}"))
    graph.add_edge(START, "plan_queries")
    graph.add_edge("plan_queries", "retrieve")
    graph.add_edge("retrieve", "feature_affinity")
    graph.add_edge("feature_affinity", "rerank")
    graph.add_conditional_edges(
        "rerank", _route("_route_after_rerank"),
        {"validate_evidence": "validate_evidence_completeness", "recover_query": "recover_query", "end": END},
    )
    graph.add_conditional_edges(
        "validate_evidence_completeness", _route("_route_after_evidence_completeness"),
        {"generate": "generate", "repair_completeness": "repair_completeness", "end": END},
    )
    graph.add_conditional_edges(
        "recover_query", lambda state: "retrieve" if state.get("queries") else "end",
        {"retrieve": "retrieve", "end": END},
    )
    graph.add_edge("generate", "validate_citations")
    graph.add_edge("validate_citations", "validate_completeness")
    graph.add_conditional_edges(
        "validate_completeness", _route("_route_after_completeness"),
        {"verify_grounding": "verify_grounding", "repair_completeness": "repair_completeness", "end": END},
    )
    graph.add_edge("repair_completeness", "retrieve")
    graph.add_edge("verify_grounding", END)
    return graph.compile()
