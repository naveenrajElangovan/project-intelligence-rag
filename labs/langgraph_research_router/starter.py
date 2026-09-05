"""Starter project: build a bounded offline LangGraph research router."""

from __future__ import annotations

import asyncio
import re
from typing import Literal, TypedDict

from langgraph.graph import END, START, StateGraph


Source = Literal["github", "jira", "confluence", "unknown"]


class ResearchState(TypedDict, total=False):
    question: str
    source: Source
    queries: tuple[str, ...]
    candidates: tuple[str, ...]
    attempt: int
    route: Literal["answer", "retry", "unavailable"]
    answer: str


EVIDENCE: dict[Source, tuple[str, ...]] = {
    "github": (
        "Authentication login is implemented in app/security.py by InternalCallerGuard.",
        "The LangGraph workflow is assembled in app/workflow_graph.py.",
    ),
    "jira": (
        "Issue PI-42 has status In Progress and is blocked by identity approval.",
    ),
    "confluence": (
        "The architecture uses a public backend and a private RAG service.",
        "Project requirements require answers to include citations.",
    ),
    "unknown": (),
}


SOURCE_KEYWORDS: dict[Source, tuple[str, ...]] = {
    "github": ("code", "implemented", "implementation", "class", "function", "file", "sign-in"),
    "jira": ("jira", "issue", "status", "priority", "blocked", "sprint"),
    "confluence": ("confluence", "architecture", "requirement", "documentation", "workflow"),
    "unknown": (),
}


RETRY_QUERY: dict[Source, str] = {
    "github": "authentication login implementation source code",
    "jira": "issue status priority blocker delivery",
    "confluence": "architecture requirements documentation workflow",
    "unknown": "",
}


def _tokens(value: str) -> set[str]:
    """Return lowercase words used by the fake lexical search."""

    return set(re.findall(r"[a-z0-9_-]+", value.casefold()))


async def classify_source(state: ResearchState) -> ResearchState:
    question_tokens = _tokens(state["question"])
    for source, keywords in SOURCE_KEYWORDS.items():
        if question_tokens & set(keywords):
            state["source"] = source
            break
    else:
        state["source"] = "unknown"
    return state


async def plan_query(state: ResearchState) -> ResearchState:
    question = state["question"]

    return {
        "queries": (question,),
        "attempt": 1,
    }


async def _search_one(source: Source, query: str) -> tuple[str, ...]:
    """Fake asynchronous search; keep this function unchanged."""

    await asyncio.sleep(0)
    query_tokens = _tokens(query)
    return tuple(
        item for item in EVIDENCE[source] if query_tokens & _tokens(item)
    )


async def search(state: ResearchState) -> ResearchState:
    """TODO 3: search all planned queries in only the selected source and deduplicate."""

    raise NotImplementedError("TODO 3: implement search")


def evaluate_evidence(state: ResearchState) -> str:
    """TODO 4: choose answer, retry, or unavailable.

    Return ``answer`` when candidates exist. Return ``retry`` only when the first
    attempt found nothing and a known source was selected. Otherwise return
    ``unavailable``.
    """

    raise NotImplementedError("TODO 4: implement evaluate_evidence")


async def retry(state: ResearchState) -> ResearchState:
    """TODO 5: append the broader query for this source and set attempt to 2."""

    raise NotImplementedError("TODO 5: implement retry")


async def answer(state: ResearchState) -> ResearchState:
    """TODO 6: join only the retrieved candidates into a grounded answer."""

    raise NotImplementedError("TODO 6: implement answer")


async def unavailable(state: ResearchState) -> ResearchState:
    """TODO 7: return a safe message stating that evidence was not found."""

    raise NotImplementedError("TODO 7: implement unavailable")


def build_graph():
    """TODO 8: assemble and compile the graph described in README.md."""

    raise NotImplementedError("TODO 8: implement build_graph")


async def run(question: str) -> ResearchState:
    """Execute the compiled graph for one question."""

    return await build_graph().ainvoke({"question": question})


if __name__ == "__main__":
    result = asyncio.run(run("Where is authentication implemented?"))
    print(result)
