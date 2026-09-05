from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any

from langgraph.errors import GraphRecursionError

from app.telemetry import stage_complete, started
from app.workflow_support.presentation import _answer_deltas, _stream_progress


async def verified_answer_events(
    answer: str,
    *,
    target_characters: int = 48,
    pacing_seconds: float = 0.012,
) -> AsyncIterator[dict[str, object]]:
    """Progressively release text only after the final answer is verified."""

    yield {"type": "answer_start"}
    for delta in _answer_deltas(answer, target_characters=target_characters):
        yield {"type": "answer_delta", "delta": delta, "verification": "verified"}
        if pacing_seconds:
            await asyncio.sleep(pacing_seconds)


async def graph_update_events(
    workflow: Any,
    state: dict[str, Any],
    status: dict[str, bool],
) -> AsyncIterator[dict[str, object]]:
    """Reduce private graph patches and expose only safe progress or answer events."""

    recursion_limit = 12 + workflow._settings.max_retrieval_attempts * 8
    # A stream writer exists for the duration of this call, and only for it. The
    # generator reads this to decide whether to emit prose and verify each
    # sentence as it completes. Left unset -- as it was -- the streaming endpoint
    # ran the buffered generator, and the caller saw nothing until generation and
    # grounding had both finished. It belongs here rather than in the workflow
    # because this function is what establishes the writer it announces.
    workflow._incremental_stream_active = True
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
                # Custom generation events may contain provisional factual text.
                # Whole-answer validation has not run yet, so none are releasable.
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
    except GraphRecursionError:
        stage_complete(
            "graph_error",
            workflow._request.project_id,
            began,
            reason_code="GRAPH_RECURSION_LIMIT",
            extra={"recursion_limit": recursion_limit},
        )
        raise
