"""Fast, explainable evaluators that run before semantic judges."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class EvaluationResult:
    name: str
    score: float
    label: str
    explanation: str

    def phoenix(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "label": self.label,
            "explanation": self.explanation,
            "annotator_kind": "CODE",
        }


def evaluate_case(case: dict[str, Any]) -> list[EvaluationResult]:
    """Evaluate a normalized response without calling a model or dependency."""

    answer = str(case.get("answer") or "")
    status = str(case.get("status") or "")
    sources = case.get("sources") or case.get("citations") or []
    expected = {str(item) for item in case.get("expected_sources", [])}
    observed = {
        str(item.get("reference") or item.get("locator") or item.get("title") or "")
        for item in sources
        if isinstance(item, dict)
    }
    allowed_project = str(case.get("project_id") or "")
    leaked = {
        str(item.get("project_id"))
        for item in case.get("candidate_metadata", [])
        if isinstance(item, dict)
        and item.get("project_id")
        and str(item.get("project_id")) != allowed_project
    }
    citation_markers = {int(value) for value in re.findall(r"\[SOURCE\s+(\d+)\]", answer, re.I)}
    citation_valid = all(1 <= marker <= len(sources) for marker in citation_markers)
    if status == "ANSWERED" and sources:
        citation_valid = citation_valid and bool(citation_markers)
    requested_language = str(case.get("language") or "")
    spanish_signal = bool(re.search(r"[¿¡áéíóúñ]|\b(?:el|la|los|las|que|para)\b", answer, re.I))
    language_valid = (requested_language == "es" and spanish_signal) or (
        requested_language == "en" and not spanish_signal
    )
    answerable = bool(case.get("answerable", True))
    refusal = status in {"ACCESS_DENIED", "INSUFFICIENT_EVIDENCE", "NEEDS_CLARIFICATION", "SOURCE_CONFLICT"}
    latency_ms = float(case.get("latency_ms") or 0)
    budget_ms = float(case.get("latency_budget_ms") or 0)
    dependency_failure = str(case.get("failure_reason") or "").startswith(("HTTP", "CONNECT", "TIMEOUT", "DEPENDENCY"))

    def result(name: str, passed: bool, explanation: str) -> EvaluationResult:
        return EvaluationResult(name, float(passed), "PASS" if passed else "FAIL", explanation)

    coverage = 1.0 if not expected else len(expected & observed) / len(expected)
    return [
        result("authorization_leakage", not leaked, "No cross-project candidates observed." if not leaked else f"Cross-project candidates: {sorted(leaked)}"),
        result("citation_validity", citation_valid, "Citation markers resolve to returned sources." if citation_valid else "A citation is missing or does not resolve."),
        result("requested_language", language_valid, f"Response matches requested language {requested_language}." if language_valid else f"Response does not match requested language {requested_language}."),
        result("response_completeness", bool(answer.strip()) and status != "", "Response has a typed status and non-empty user text."),
        result("refusal_typing", refusal == (status != "ANSWERED"), "Refusal and status agree."),
        EvaluationResult("source_coverage", coverage, "PASS" if coverage == 1 else "FAIL", f"Matched {len(expected & observed)} of {len(expected)} expected sources."),
        result("latency_budget", not budget_ms or latency_ms <= budget_ms, f"Latency {latency_ms:.0f} ms; budget {budget_ms:.0f} ms."),
        result("dependency_classification", not dependency_failure or status != "ANSWERED", "Dependency failures are not mislabeled as answered."),
        result("refusal_appropriateness", refusal == (not answerable), "Refusal agrees with reviewed answerability."),
    ]
