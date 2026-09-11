import asyncio
from types import SimpleNamespace
import pytest
from fastapi import HTTPException
from app import main


def test_accelerator_failure_is_not_reported_as_chroma(monkeypatch):
    monkeypatch.setattr(main.app.state, "lexical_corpus_ready", True)
    calls = []

    async def worker(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise ConnectionError("private details must not be exposed")

    monkeypatch.setattr(main.asyncio, "to_thread", worker)
    settings = SimpleNamespace(
        llm_configured=True,
        chroma_host="chroma",
        chroma_port=8000,
        local_accelerator_url="http://worker",
        internal_api_key="private",
        llm_provider="ollama",
    )
    with pytest.raises(HTTPException) as failure:
        asyncio.run(main.ready(settings))
    assert failure.value.status_code == 503
    assert "local inference accelerator" in failure.value.detail
    assert "private" not in failure.value.detail
