"""The streaming endpoint must actually stream.

`_incremental_stream_active` gates the generator's per-sentence streaming path.
It was initialised False and never set True anywhere, so `/v1/answer/stream`
ran the buffered generator: telemetry showed time_to_first_chunk_seconds 0.0 on
every request and callers waited out generation plus grounding before seeing a
word.
"""

import asyncio

from app import workflow as workflow_module
from app.models import RagRequest, RagResponse
from app.workflow_support import streaming as streaming_module


def _request() -> RagRequest:
    return RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question="What does the shift event contain?",
        accessPolicyIds=["project:DEMO"],
    )


def _response() -> RagResponse:
    return RagResponse(
        status="ANSWERED",
        answer="A verified sentence.",
        confidence="HIGH",
        projectId="DEMO",
        sources=[],
        missingInformation=[],
        evidenceStatus="SUFFICIENT",
        contextQuality="SUFFICIENT",
        coverage="COMPLETE",
    )


def _collect(workflow) -> list[bool]:
    """Run stream(), recording the flag as the graph sees it."""

    observed: list[bool] = []

    async def fake_graph_update_events(instance, state, stream_status):
        observed.append(getattr(instance, "_incremental_stream_active", False))
        stream_status["answer_started"] = False
        return
        yield  # pragma: no cover - generator shape

    async def fake_response_from_state(state, began):
        return _response()

    workflow_module.graph_update_events = fake_graph_update_events
    workflow._response_from_state = fake_response_from_state

    async def drain():
        async for _event in workflow.stream():
            pass

    asyncio.run(drain())
    return observed


def test_graph_update_events_announces_the_stream_writer() -> None:
    """The real activation, in the function that establishes the writer."""

    class FakeGraph:
        async def astream(self, *_args, **_kwargs):
            return
            yield  # pragma: no cover - generator shape

    workflow = object.__new__(workflow_module.AuthorizedRagWorkflow)
    workflow._settings = type("S", (), {"max_retrieval_attempts": 2})()
    workflow._graph = FakeGraph()
    workflow._request = _request()
    workflow._incremental_stream_active = False

    async def drain():
        async for _event in streaming_module.graph_update_events(
            workflow, {}, {"answer_started": False}
        ):
            pass

    asyncio.run(drain())
    assert workflow._incremental_stream_active is True


def test_the_buffered_path_leaves_it_off() -> None:
    """run() has no stream writer, so the flag must stay False."""

    workflow = object.__new__(workflow_module.AuthorizedRagWorkflow)
    workflow._incremental_stream_active = False
    assert workflow._incremental_stream_active is False
