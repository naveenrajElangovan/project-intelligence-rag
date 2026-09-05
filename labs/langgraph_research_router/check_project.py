"""Offline acceptance checker for the beginner LangGraph project."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from starter import run


@dataclass(frozen=True)
class Scenario:
    name: str
    question: str
    expected_source: str
    expected_route: str
    expected_attempt: int
    expected_text: str


SCENARIOS = (
    Scenario(
        "GitHub question",
        "Where is the LangGraph workflow implemented in code?",
        "github",
        "answer",
        1,
        "workflow_graph.py",
    ),
    Scenario(
        "Jira question",
        "What is the status of Jira issue PI-42?",
        "jira",
        "answer",
        1,
        "In Progress",
    ),
    Scenario(
        "Confluence question",
        "What does the architecture documentation say?",
        "confluence",
        "answer",
        1,
        "private RAG service",
    ),
    Scenario(
        "One bounded retry",
        "Where is sign-in handled?",
        "github",
        "answer",
        2,
        "security.py",
    ),
    Scenario(
        "Safe unavailable route",
        "What is the orbital period of Neptune?",
        "unknown",
        "unavailable",
        1,
        "not find",
    ),
)


async def check() -> None:
    failures: list[str] = []
    for scenario in SCENARIOS:
        try:
            result = await run(scenario.question)
        except NotImplementedError as error:
            raise SystemExit(f"Project is not finished: {error}") from error
        except Exception as error:
            failures.append(f"{scenario.name}: raised {type(error).__name__}: {error}")
            continue

        checks = {
            "source": result.get("source") == scenario.expected_source,
            "route": result.get("route") == scenario.expected_route,
            "attempt": result.get("attempt") == scenario.expected_attempt,
            "answer text": scenario.expected_text.casefold()
            in str(result.get("answer", "")).casefold(),
            "bounded attempts": int(result.get("attempt", 99)) <= 2,
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            failures.append(
                f"{scenario.name}: failed {', '.join(failed)}; state={result}"
            )
        else:
            print(f"PASS: {scenario.name}")

    if failures:
        print("\nFAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("\nAll LangGraph project scenarios passed.")


if __name__ == "__main__":
    asyncio.run(check())
