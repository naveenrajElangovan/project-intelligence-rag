"""Evaluation-only access to final workflow evidence, outside the HTTP contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.models import RagResponse
from app.telemetry import started
from app.workflow_support.execution import invoke_bounded_graph
from app.workflow_support.fail_closed import clarification_response
from app.workflow_support.json_transform import json_transform_response
from app.workflow_support.query_analysis import resolve_response_language


@dataclass(frozen=True)
class WorkflowEvaluationResult:
    response: RagResponse
    retrieved_contexts: tuple[str, ...]
    query_language: str
    uncited_claims_dropped: int = 0
    answer_style: str = ""
    context_relevance: float = -1.0
    answer_relevance: float = -1.0
    pre_gate_draft_answer: str = ""
    answer_relevance_scorer_question: str = ""
    answer_relevance_scorer_answer: str = ""
    canonical_fallback_used: bool = False
    canonical_fallback_reason: str = ""
    generated_outcome: str = ""
    generated_refusal_reason: str = ""


class EvaluationWorkflowMixin:
    """Execute the same graph and final output gate while retaining local evidence."""

    _request: Any
    _settings: Any
    _vocabulary: Any
    _graph: Any

    async def run_for_evaluation(self) -> WorkflowEvaluationResult:
        began = started()
        deterministic = json_transform_response(self._request, began)
        if deterministic is not None:
            return WorkflowEvaluationResult(
                deterministic, (), resolve_response_language(self._request.question)
            )
        clarification = clarification_response(
            self._request,
            self._vocabulary.entities,
            getattr(self._vocabulary, "source_types", ()),
        )
        if clarification is not None:
            return WorkflowEvaluationResult(
                clarification, (), resolve_response_language(self._request.question)
            )
        state = await invoke_bounded_graph(
            self._graph,
            {"request": self._request, "_workflow": self},
            project_id=self._request.project_id,
            max_retrieval_attempts=self._settings.max_retrieval_attempts,
            began=began,
        )
        response = await self._response_from_state(state, began)
        return WorkflowEvaluationResult(
            response=response,
            retrieved_contexts=tuple(
                document.page_content for document in state.get("documents", [])
            ),
            query_language=(
                state.get("language")
                or resolve_response_language(self._request.question)
            ),
            uncited_claims_dropped=int(state.get("uncited_claims_dropped", 0)),
            answer_style=str(state.get("answer_style") or ""),
            context_relevance=float(state.get("context_relevance", -1.0)),
            answer_relevance=float(state.get("answer_relevance", -1.0)),
            pre_gate_draft_answer=str(state.get("pre_gate_draft_answer") or ""),
            answer_relevance_scorer_question=str(
                state.get("answer_relevance_scorer_question") or ""
            ),
            answer_relevance_scorer_answer=str(
                state.get("answer_relevance_scorer_answer") or ""
            ),
            canonical_fallback_used=bool(state.get("canonical_fallback_used", False)),
            canonical_fallback_reason=str(
                state.get("canonical_fallback_reason") or ""
            ),
            generated_outcome=str(state.get("generated_outcome") or ""),
            generated_refusal_reason=str(
                state.get("generated_refusal_reason") or ""
            ),
        )
