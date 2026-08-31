from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langgraph.errors import GraphRecursionError

from app.llm import GroundedAnswer
from app.telemetry import stage_complete, started
from app.workflow_support.presentation import (
    _incrementally_verified_events,
    _stream_progress,
)


async def graph_update_events(
    workflow: Any,
    state: dict[str, Any],
    status: dict[str, bool],
) -> AsyncIterator[dict[str, object]]:
    """Reduce private graph patches and expose only safe progress or answer events."""

    recursion_limit = 12 + workflow._settings.max_retrieval_attempts * 8
    began = started()
    try:
        async for update in workflow._graph.astream(
            state,
            config={"recursion_limit": recursion_limit},
            stream_mode=["updates", "custom"],
        ):
            if (
                isinstance(update, tuple)
                and len(update) == 2
                and update[0] == "custom"
            ):
                event = update[1]
                if not isinstance(event, dict):
                    continue
                if not status["answer_started"]:
                    yield {"type": "answer_start"}
                    status["answer_started"] = True
                yield event
                continue
            if isinstance(update, tuple) and len(update) == 2:
                update = update[1]
            if not isinstance(update, dict):
                continue
            for node_name, patch in update.items():
                if isinstance(patch, dict):
                    state.update(patch)
                progress = _stream_progress(
                    node_name, state.get("language", "en"), state
                )
                if progress is not None:
                    yield progress
                if (
                    workflow._settings.incremental_verified_streaming_enabled
                    and node_name == "generate"
                    and not status["answer_started"]
                    and isinstance(state.get("generated"), GroundedAnswer)
                ):
                    yield {"type": "answer_start"}
                    status["answer_started"] = True
                    async for event in _incrementally_verified_events(
                        workflow._grounding_verifier,
                        question=workflow._request.question,
                        documents=state.get("documents", []),
                        generated=state["generated"],
                        language=state.get("language", ""),
                    ):
                        yield event
    except GraphRecursionError:
        stage_complete(
            "graph_error",
            workflow._request.project_id,
            began,
            reason_code="GRAPH_RECURSION_LIMIT",
            extra={"recursion_limit": recursion_limit},
        )
        raise
