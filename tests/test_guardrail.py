from fastapi.testclient import TestClient
import asyncio
import pytest
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.llm import TokenUsage
from app.main import app
from app import main as main_module
from app.security import ProjectRateLimiter


def settings() -> Settings:
    return Settings(_env_file=None, environment="development", internal_api_key="x" * 32)


def test_rejects_direct_call_without_internal_credential() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(
        _env_file=None, environment="production", internal_api_key="x" * 32,
        llm_provider="openai",
        openai_api_key="openai-key", docs_enabled=False, force_https=True,
        allowed_hosts="rag", chroma_host="chroma.internal"
    )
    try:
        response = TestClient(app).post(
            "/v1/answer",
            json={
                "projectId": "DEMO",
                "collectionName": "project-intelligence",
                "textField": "chunk_text",
                "question": "What is the status?",
                "accessPolicyIds": ["project:DEMO"],
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 401


def test_allows_private_development_call_when_internal_key_is_omitted() -> None:
    development = lambda: Settings(_env_file=None, environment="development")
    app.dependency_overrides[get_settings] = development
    try:
        response = TestClient(app).post(
            "/v1/answer",
            json={
                "projectId": "DEMO",
                "collectionName": "project-intelligence",
                "textField": "chunk_text",
                "question": "Tell me about AAOS",
                "accessPolicyIds": ["project:AAOS"],
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["confidence"] == "NONE"


def test_returns_model_written_no_access_before_retrieval(monkeypatch) -> None:
    class FakeSafeResponseGenerator:
        def __init__(self, *args) -> None:
            self.last_usage = TokenUsage(input_tokens=12, output_tokens=8)
            self.model_name = "safe-test-model"

        async def generate(self, question, language, reason) -> str:
            assert question == "Tell me about AAOS"
            assert language == "en"
            assert reason == "NO_ACCESS"
            return "I can’t help with that request under your current access."

    monkeypatch.setattr(
        main_module, "LangChainSafeResponseGenerator", FakeSafeResponseGenerator
    )
    app.dependency_overrides[get_settings] = settings
    try:
        response = TestClient(app).post(
            "/v1/answer",
            headers={"Authorization": f"Bearer {settings().internal_api_key}"},
            json={
                "projectId": "DEMO",
                "collectionName": "project-intelligence",
                "textField": "chunk_text",
                "question": "Tell me about AAOS",
                "accessPolicyIds": ["project:AAOS"],
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert response.json()["confidence"] == "NONE"
    assert response.json()["sources"] == []
    assert response.json()["answer"] == (
        "I can’t help with that request under your current access."
    )


def test_rejects_incompatible_live_schema_before_retrieval() -> None:
    app.dependency_overrides[get_settings] = settings
    try:
        response = TestClient(app).post(
            "/v1/answer",
            headers={"Authorization": f"Bearer {settings().internal_api_key}"},
            json={
                "projectId": "DEMO",
                "collectionName": "project-intelligence",
                "textField": "chunk_text",
                "embeddingModel": "multilingual-e5-large",
                "schemaVersion": "2",
                "question": "How are project retrieval filters enforced?",
                "accessPolicyIds": ["project:DEMO"],
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 409


def test_environment_has_no_implicit_default(monkeypatch) -> None:
    monkeypatch.delenv("PI_RAG_ENVIRONMENT", raising=False)
    with pytest.raises(ValidationError, match="environment"):
        Settings(_env_file=None)


def test_non_development_environment_requires_a_key() -> None:
    with pytest.raises(ValidationError, match="INTERNAL_API_KEY"):
        Settings(_env_file=None, environment="staging")


def test_supported_schema_contracts_must_not_be_empty() -> None:
    with pytest.raises(ValidationError, match="SUPPORTED_SCHEMA_VERSIONS"):
        Settings(
            _env_file=None,
            environment="development",
            supported_schema_versions=(),
        )


def test_rate_limit_is_isolated_by_project() -> None:
    limiter = ProjectRateLimiter(1)

    async def exercise() -> None:
        await limiter.acquire("alpha")
        await limiter.acquire("beta")
        with pytest.raises(Exception) as failure:
            await limiter.acquire("alpha")
        assert getattr(failure.value, "status_code", None) == 429

    asyncio.run(exercise())


def test_streamed_body_is_rejected_by_received_bytes() -> None:
    response = TestClient(app).post(
        "/v1/answer",
        content=b"{" + b"x" * 300_000 + b"}",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_request_timeout_must_exceed_stream_total_timeout() -> None:
    with pytest.raises(ValidationError, match="must exceed.*STREAM_TOTAL"):
        Settings(
            _env_file=None,
            environment="development",
            llm_stream_total_timeout_seconds=180,
            request_timeout_seconds=180,
        )


def test_request_timeout_must_cover_non_streamed_retry_budget() -> None:
    with pytest.raises(ValidationError, match="non-streamed LLM retry budget"):
        Settings(
            _env_file=None,
            environment="development",
            llm_stream_total_timeout_seconds=60,
            request_timeout_seconds=80,
            llm_timeout_seconds=45,
            llm_retry_attempts=2,
        )
