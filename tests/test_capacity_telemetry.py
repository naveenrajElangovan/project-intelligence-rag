import asyncio

import pytest
from fastapi import HTTPException
from prometheus_client import REGISTRY

from app.config import Settings
from app.main import _acquire_request_slot


def _sample(name: str, labels: dict[str, str] | None = None) -> float:
    value = REGISTRY.get_sample_value(name, labels or {})
    return value or 0.0


def test_request_capacity_metrics_track_accept_release_and_shed() -> None:
    async def scenario() -> None:
        settings = Settings(
            _env_file=None,
            max_inflight_requests=1,
            local_max_concurrency=1,
            load_shed_wait_seconds=0.001,
        )
        accepted_before = _sample(
            "pi_rag_request_admissions_total", {"outcome": "accepted"}
        )
        shed_before = _sample(
            "pi_rag_request_admissions_total", {"outcome": "shed"}
        )
        slot = await _acquire_request_slot(settings)
        assert _sample("pi_rag_inflight_requests") >= 1
        with pytest.raises(HTTPException) as raised:
            await _acquire_request_slot(settings)
        assert raised.value.status_code == 503
        slot.release()

        assert _sample(
            "pi_rag_request_admissions_total", {"outcome": "accepted"}
        ) == accepted_before + 1
        assert _sample(
            "pi_rag_request_admissions_total", {"outcome": "shed"}
        ) == shed_before + 1

    asyncio.run(scenario())
