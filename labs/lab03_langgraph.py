"""Lab 3: a small offline version of the production bounded graph."""

import asyncio
from typing import TypedDict

from langgraph.graph import END, START, StateGraph


class State(TypedDict, total=False):
    question: str
    queries: tuple[str, ...]
    candidates: tuple[str, ...]
    route: str


async def plan(state: State) -> State:
    return {"queries": (state["question"], "How is project authorization applied?")}


async def retrieve(state: State) -> State:
    branches = await asyncio.gather(*(_search(query) for query in state["queries"]))
    return {"candidates": tuple(dict.fromkeys(item for branch in branches for item in branch))}


async def _search(query: str) -> tuple[str, ...]:
    return ("authorized-chunk",) if query else ()


async def grounded(state: State) -> State:
    return {"route": "grounded"}


async def unavailable(state: State) -> State:
    return {"route": "unavailable"}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("plan", plan)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grounded", grounded)
    graph.add_node("unavailable", unavailable)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "retrieve")
    graph.add_conditional_edges(
        "retrieve", lambda state: "grounded" if state["candidates"] else "unavailable"
    )
    graph.add_edge("grounded", END)
    graph.add_edge("unavailable", END)
    return graph.compile()


async def run() -> State:
    return await build_graph().ainvoke({"question": "¿Cómo se aplica la autorización?"})


if __name__ == "__main__":
    print(asyncio.run(run()))
