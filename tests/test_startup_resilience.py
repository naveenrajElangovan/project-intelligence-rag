"""Startup must not hang or die because a downstream is down.

Observed in `.run/rag.log`: the process printed "Loading weights", then nothing --
no "Application startup complete", no /health, no error. The lexical corpus
warm-up reads every authorized collection out of Chroma inside the lifespan, and
with Chroma unavailable the client retried in there indefinitely. The launcher's
health poll then failed and the service looked crashed while the process was
alive and stuck.

Liveness must not depend on a downstream. Readiness may, and /ready already
distinguishes the two.
"""

from __future__ import annotations

import asyncio

import pytest

from app import main as main_module
from app.config import Settings


def _settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="development",
        warm_local_models_on_startup=False,
        warm_local_embedder_on_startup=False,
        lexical_corpus_warm_timeout_seconds=1.0,
        lexical_corpus_warm_retry_seconds=1.0,
    )


@pytest.fixture(autouse=True)
def _no_real_models(monkeypatch):
    monkeypatch.setattr(main_module, "build_embedder", lambda settings: object())
    monkeypatch.setattr(main_module, "build_reranker", lambda settings: object())
    monkeypatch.setattr(main_module, "warm_embedder", lambda embedder: None)


async def _run_lifespan(monkeypatch, settings, warm) -> bool:
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "warm_authorized_lexical_corpora", warm)

    class Application:
        class state:  # noqa: N801 - mirrors FastAPI's app.state attribute bag
            lexical_corpus_ready = None

    application = Application()
    async with main_module.lifespan(application):
        await asyncio.sleep(0)
    return application.state.lexical_corpus_ready


def test_startup_completes_when_chroma_is_unreachable(monkeypatch) -> None:
    async def warm(settings, embedder):
        raise ConnectionError("chroma: connection refused")

    ready = asyncio.run(_run_lifespan(monkeypatch, _settings(), warm))

    assert ready is False


def test_startup_completes_when_the_warm_up_hangs(monkeypatch) -> None:
    """The hang, not the error, is what made this look like a crash."""

    async def warm(settings, embedder):
        await asyncio.sleep(30)

    async def scenario():
        return await asyncio.wait_for(
            _run_lifespan(monkeypatch, _settings(), warm), timeout=10
        )

    ready = asyncio.run(scenario())

    assert ready is False


def test_a_successful_warm_up_marks_the_corpus_ready(monkeypatch) -> None:
    async def warm(settings, embedder):
        return None

    ready = asyncio.run(_run_lifespan(monkeypatch, _settings(), warm))

    assert ready is True


def test_readiness_recovers_when_chroma_returns(monkeypatch) -> None:
    attempts = 0

    async def warm(settings, embedder):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("chroma: connection refused")

    async def scenario():
        settings = _settings()
        settings.lexical_corpus_warm_retry_seconds = 0.01
        monkeypatch.setattr(main_module, "get_settings", lambda: settings)
        monkeypatch.setattr(main_module, "warm_authorized_lexical_corpora", warm)

        class Application:
            class state:  # noqa: N801
                lexical_corpus_ready = None

        application = Application()
        async with main_module.lifespan(application):
            for _ in range(20):
                if application.state.lexical_corpus_ready:
                    break
                await asyncio.sleep(0.01)
            return application.state.lexical_corpus_ready

    assert asyncio.run(scenario()) is True
    assert attempts == 2
