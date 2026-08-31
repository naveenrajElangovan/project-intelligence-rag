import json
import types

import asyncio
from langchain_core.documents import Document
import pytest

from fastapi.testclient import TestClient

from app import main as main_module
from app.config import Settings, get_settings
from app.main import app
from app.workflow import _answer_deltas, _stream_progress
from app.llm import (
    GroundedAnswer,
    GroundingVerdict,
    ModelSlotUnavailableError,
    StreamTimeoutError,
    _LOCAL_SEMAPHORES,
    _citations_from_answer,
    _stream_grounded_answer_with_usage,
    _stream_plain_answer_with_usage,
    _model_slot,
)
from app.models import RagRequest, RagResponse


def _settings() -> Settings:
    """Provide an isolated internal-service configuration for stream tests."""

    return Settings(_env_file=None, environment="development", internal_api_key="x" * 32)


def test_answer_deltas_reconstruct_verified_markdown() -> None:
    answer = "## Result\n\n- First supported item\n- Second supported item"
    assert "".join(_answer_deltas(answer, target_characters=12)) == answer


def test_deterministic_finished_text_is_a_snapshot_not_simulated_deltas() -> None:
    workflow = object.__new__(main_module.AuthorizedRagWorkflow)
    workflow._request = RagRequest(
        projectId="DEMO",
        collectionName="project-intelligence",
        question='{"status":"ok","count":2}',
        accessPolicyIds=["project:DEMO"],
    )

    events = asyncio.run(_collect(workflow.stream()))

    assert [event["type"] for event in events] == [
        "answer_start",
        "answer_snapshot",
        "complete",
    ]
    assert events[1]["answer"] == events[-1]["response"]["answer"]


def test_progress_events_are_localized_and_content_free() -> None:
    event = _stream_progress("rerank", "es")
    assert event == {
        "type": "status",
        "stage": "ranking",
        "message": "Seleccionando la evidencia más sólida…",
    }


def test_stream_endpoint_forwards_only_workflow_events(monkeypatch) -> None:
    class FakeWorkflow:
        """Emit a deterministic verified stream without touching project evidence."""

        def __init__(self, *_args) -> None:
            pass

        async def stream(self):
            yield {"type": "status", "stage": "retrieving", "message": "Searching…"}
            yield {"type": "answer_start"}
            yield {"type": "answer_delta", "delta": "Grounded answer."}
            yield {
                "type": "complete",
                "response": {
                    "answer": "Grounded answer.",
                    "confidence": "HIGH",
                    "projectId": "DEMO",
                    "sources": [],
                    "missingInformation": [],
                },
            }

    monkeypatch.setattr(main_module, "AuthorizedRagWorkflow", FakeWorkflow)
    app.dependency_overrides[get_settings] = _settings
    try:
        response = TestClient(app).post(
            "/v1/answer/stream",
            headers={"Authorization": f"Bearer {_settings().internal_api_key}"},
            json={
                "projectId": "DEMO",
                "collectionName": "project-intelligence",
                "question": "What does POS do?",
                "accessPolicyIds": ["project:DEMO"],
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == [
        "status",
        "answer_start",
        "answer_delta",
        "complete",
    ]
    assert events[-1]["response"]["answer"] == "Grounded answer."


def test_stream_timeout_uses_static_error_without_another_llm_call(
    monkeypatch, caplog
) -> None:
    class TimedOutWorkflow:
        def __init__(self, *_args) -> None:
            pass

        async def stream(self):
            if False:
                yield {}
            raise TimeoutError("stream_idle_timeout")

    class ForbiddenSafeGenerator:
        def __init__(self, *_args) -> None:
            raise AssertionError("timeout handling must not call an LLM")

    monkeypatch.setattr(main_module, "AuthorizedRagWorkflow", TimedOutWorkflow)
    monkeypatch.setattr(
        main_module, "LangChainSafeResponseGenerator", ForbiddenSafeGenerator
    )
    caplog.set_level("INFO", logger="project_intelligence.rag.stages")
    main_module.LOGGER.addHandler(caplog.handler)
    app.dependency_overrides[get_settings] = _settings
    try:
        response = TestClient(app).post(
            "/v1/answer/stream",
            headers={"Authorization": f"Bearer {_settings().internal_api_key}"},
            json={
                "projectId": "DEMO",
                "collectionName": "project-intelligence",
                "question": "What does POS do?",
                "accessPolicyIds": ["project:DEMO"],
            },
        )
    finally:
        app.dependency_overrides.clear()
        main_module.LOGGER.removeHandler(caplog.handler)
    assert response.status_code == 200
    events = [json.loads(line) for line in response.text.splitlines()]
    assert [event["type"] for event in events] == ["error"]
    failure_record = next(
        record for record in caplog.records if '"event":"rag_stream_failure"' in record.message
    )
    assert failure_record.exc_info is not None
    assert '"exception_type":"TimeoutError"' in failure_record.message
    assert '"exception_message":"stream_idle_timeout"' in failure_record.message
    completion = next(
        json.loads(record.message)
        for record in caplog.records
        if '"event":"rag_request_complete"' in record.message
    )
    assert completion["outcome"] == "FAILED"
    assert completion["reason_code"] == "TIMEOUTERROR"


def test_incremental_stream_never_labels_a_failed_sentence_verified() -> None:
    request = RagRequest(
        projectId="second-project",
        collectionName="project-intelligence",
        question="What behavior is supported?",
        accessPolicyIds=["project:second-project"],
    )
    workflow = object.__new__(main_module.AuthorizedRagWorkflow)
    workflow._settings = Settings(
        _env_file=None,
        environment="development",
        incremental_verified_streaming_enabled=True,
    )
    workflow._request = request

    class Graph:
        async def astream(self, _state, stream_mode, config):
            assert stream_mode == ["updates", "custom"]
            assert config["recursion_limit"] > 25
            yield {
                "generate": {
                    "generated": GroundedAnswer(
                        answer=(
                            "Supported project behavior is present [SOURCE 1]. "
                            "Invented project behavior is also present [SOURCE 1]."
                        ),
                        citations=[1],
                    ),
                    "documents": [Document(page_content="Supported project behavior")],
                    "language": "en",
                    "grounded": True,
                }
            }

    class Verifier:
        async def verify(self, _question, _documents, answer, **_kwargs):
            supported = answer.answer.startswith("Supported")
            return GroundingVerdict(
                supported=supported,
                unsupported_claims=[] if supported else [answer.answer],
                reason_code="SUPPORTED" if supported else "UNSUPPORTED_CLAIM",
            )

    async def response_from_state(self, _state, _began):
        return RagResponse(
            answer="Supported project behavior is present.",
            confidence="HIGH",
            projectId="second-project",
            sources=[],
            missingInformation=[],
        )

    workflow._graph = Graph()
    workflow._grounding_verifier = Verifier()
    workflow._response_from_state = types.MethodType(response_from_state, workflow)
    events = asyncio.run(_collect(workflow.stream()))
    verified = "".join(
        str(event.get("delta") or "")
        for event in events
        if event.get("verification") == "verified"
    )
    assert "Supported project behavior" in verified
    assert "Invented project behavior" not in verified
    assert any(event["type"] == "answer_sentence_rejected" for event in events)


def test_structured_generation_releases_each_citation_complete_sentence_early() -> None:
    class PartialStructuredAnswer:
        async def astream(self, _inputs):
            yield {"answer": "First supported claim"}
            yield {"answer": "First supported claim [SOURCE 1]. Second"}
            yield {
                "answer": (
                    "First supported claim [SOURCE 1]. "
                    "Second supported claim [SOURCE 2]."
                ),
                "citations": [1, 2],
                "missing_information": [],
            }

    released: list[str] = []

    async def release(sentence: str, _index: int) -> None:
        released.append(sentence)

    value, _usage = asyncio.run(
        _stream_grounded_answer_with_usage(
            PartialStructuredAnswer(), {}, _settings(), release
        )
    )
    assert value.citations == [1, 2]
    assert released == [
        "First supported claim [SOURCE 1].",
        "Second supported claim [SOURCE 2].",
    ]


def test_plain_generation_streams_deltas_before_sentence_verification() -> None:
    class Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class PlainAnswer:
        async def astream(self, _inputs):
            yield Chunk("First supported ")
            yield Chunk("claim [SOURCE 1]. ")
            yield Chunk("Second supported claim [SOURCE 2].")

    events: list[tuple[str, str]] = []

    async def delta(value: str) -> None:
        events.append(("delta", value))

    async def sentence(value: str, _index: int) -> None:
        events.append(("sentence", value))

    answer, _usage = asyncio.run(
        _stream_plain_answer_with_usage(
            PlainAnswer(),
            {},
            _settings(),
            delta_callback=delta,
            sentence_callback=sentence,
        )
    )

    assert answer.endswith("Second supported claim [SOURCE 2].")
    assert events[0] == ("delta", "First supported ")
    assert events.index(("sentence", "First supported claim [SOURCE 1].")) > 0


async def _collect(stream):
    return [event async for event in stream]


@pytest.mark.parametrize(
    ("answer", "metadata_citations"),
    [
        ("Claim [SOURCE 1].", [1]),
        ("A [SOURCE 2]. B [SOURCE 1].", [1, 2]),
        ("Repeated [SOURCE 3] and again [SOURCE 3].", [3]),
        ("No citation.", []),
        ("[SOURCE 10]", [10]),
        ("A [SOURCE 4]. B [SOURCE 8].", [4, 8]),
        ("A [SOURCE 9] [SOURCE 2].", [2, 9]),
        ("Lowercase [source 1] is not a contract reference.", []),
        ("Malformed [SOURCE x].", []),
        ("Malformed [SOURCE 1a].", []),
        ("A [SOURCE 12]. B [SOURCE 11].", [11, 12]),
        ("Table | value [SOURCE 5] |", [5]),
        ("Bullet [SOURCE 6].", [6]),
        ("One [SOURCE 1]. Two [SOURCE 20].", [1, 20]),
        ("Adjacent [SOURCE 7][SOURCE 8].", [7, 8]),
        ("Parenthetical ([SOURCE 13]).", [13]),
        ("Newline\n[SOURCE 14].", [14]),
        ("Unicode text [SOURCE 15].", [15]),
        ("Zero remains parseable [SOURCE 0].", [0]),
        ("Three [SOURCE 3], [SOURCE 1], [SOURCE 2].", [1, 2, 3]),
    ],
)
def test_regex_citations_match_metadata_contract(
    answer: str, metadata_citations: list[int]
) -> None:
    assert _citations_from_answer(answer) == metadata_citations


def test_plain_stream_reports_idle_timeout_with_verified_partial_text() -> None:
    class Chunk:
        def __init__(self, content: str) -> None:
            self.content = content

    class StalledAnswer:
        async def astream(self, _inputs):
            yield Chunk("Verified claim [SOURCE 1].")
            await asyncio.sleep(0.05)
            yield Chunk("Never reached")

    async def sentence(value: str, _index: int) -> bool:
        return value.startswith("Verified")

    settings = Settings(
        _env_file=None,
        environment="development",
        llm_stream_idle_timeout_seconds=0.01,
        llm_stream_total_timeout_seconds=1.0,
    )
    with pytest.raises(StreamTimeoutError) as captured:
        asyncio.run(
            _stream_plain_answer_with_usage(
                StalledAnswer(),
                {},
                settings,
                delta_callback=None,
                sentence_callback=sentence,
            )
        )
    assert captured.value.kind == "stream_idle_timeout"
    assert captured.value.verified_sentences == ("Verified claim [SOURCE 1].",)


def test_plain_stream_reports_total_timeout_separately() -> None:
    class Chunk:
        content = "still working "

    class EndlessAnswer:
        async def astream(self, _inputs):
            while True:
                await asyncio.sleep(0.005)
                yield Chunk()

    async def sentence(_value: str, _index: int) -> bool:
        return True

    settings = Settings(
        _env_file=None,
        environment="development",
        llm_stream_idle_timeout_seconds=0.01,
        llm_stream_total_timeout_seconds=0.03,
    )
    with pytest.raises(StreamTimeoutError) as captured:
        asyncio.run(
            _stream_plain_answer_with_usage(
                EndlessAnswer(),
                {},
                settings,
                delta_callback=None,
                sentence_callback=sentence,
            )
        )
    assert captured.value.kind == "stream_total_timeout"


def test_three_local_requests_are_load_shed_instead_of_outer_timing_out() -> None:
    async def exercise() -> list[str]:
        _LOCAL_SEMAPHORES.clear()
        settings = Settings(
            _env_file=None,
            environment="development",
            local_max_concurrency=1,
            load_shed_wait_seconds=0.01,
        )
        release = asyncio.Event()

        async def request(index: int) -> str:
            try:
                async with _model_slot(settings):
                    if index == 0:
                        await release.wait()
                    return "served"
            except ModelSlotUnavailableError:
                return "shed"

        first = asyncio.create_task(request(0))
        await asyncio.sleep(0)
        queued = [asyncio.create_task(request(index)) for index in (1, 2)]
        results = await asyncio.gather(*queued)
        release.set()
        return [await first, *results]

    assert asyncio.run(exercise()) == ["served", "shed", "shed"]
