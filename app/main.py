import asyncio
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import re

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request, status
from langchain_core.documents import Document
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response, StreamingResponse
from starlette.middleware.httpsredirect import HTTPSRedirectMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import Settings, get_settings
from app.llm import (
    LangChainSafeResponseGenerator,
    no_access_answer,
    pipeline_unavailable_answer,
)
from app.models import RagRequest, RagResponse
from app.embedding import build_embedder, warm_embedder
from app.reranking import build_reranker
from app.retrieval import warm_authorized_lexical_corpora
from app.security import ProjectRateLimiter, RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.security import require_internal_caller
from app.workflow import AuthorizedRagWorkflow, detect_query_language
from app.telemetry import (
    configure_telemetry_logging,
    new_request_id,
    request_complete,
    request_id,
    reset_request_id,
    set_request_id,
    stage_complete,
    started,
)


@asynccontextmanager
async def lifespan(_application: FastAPI):
    """Warm latency-sensitive local models, then serve requests."""

    settings = get_settings()
    _application.state.lexical_corpus_ready = not (
        settings.lexical_fallback_enabled
        and settings.warm_lexical_corpus_on_startup
    )
    if settings.warm_local_models_on_startup:
        reranker = build_reranker(settings)
        await reranker.rerank(
            "project knowledge",
            [
                Document(
                    page_content="Project knowledge warm-up sample.",
                    metadata={"source_id": "startup-warmup", "score": 1.0},
                )
            ],
            score_threshold=0.0,
            top_n=1,
        )
    embedder = build_embedder(settings)
    if settings.warm_local_embedder_on_startup:
        warm_embedder(embedder)
    if settings.lexical_fallback_enabled and settings.warm_lexical_corpus_on_startup:
        await warm_authorized_lexical_corpora(settings, embedder)
        _application.state.lexical_corpus_ready = True
    yield


def create_app() -> FastAPI:
    """Build the private RAG API with production security middleware."""

    settings = get_settings()
    configure_telemetry_logging()
    if settings.environment.strip().lower() == "production":
        os.environ["LANGCHAIN_TRACING_V2"] = "false"
        os.environ["LANGSMITH_TRACING"] = "false"
    application = FastAPI(
        title="Project Intelligence RAG",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
        lifespan=lifespan,
    )
    application.add_middleware(
        TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list
    )
    if settings.force_https:
        application.add_middleware(HTTPSRedirectMiddleware)
    application.add_middleware(
        RequestSizeLimitMiddleware, maximum_bytes=settings.max_request_body_bytes
    )
    application.add_middleware(SecurityHeadersMiddleware, hsts=settings.force_https)
    application.state.project_rate_limiter = ProjectRateLimiter(
        settings.rate_limit_per_minute
    )
    application.state.lexical_corpus_ready = not (
        settings.lexical_fallback_enabled
        and settings.warm_lexical_corpus_on_startup
    )
    return application


app = create_app()

LOGGER = logging.getLogger("project_intelligence.rag.stages")

_REQUEST_SEMAPHORES: dict[tuple[int, int], asyncio.Semaphore] = {}


async def _acquire_request_slot(settings: Settings) -> asyncio.Semaphore:
    """Acquire capacity before retrieval or reject the request immediately."""

    loop = asyncio.get_running_loop()
    key = (id(loop), settings.max_inflight_requests)
    semaphore = _REQUEST_SEMAPHORES.setdefault(
        key, asyncio.Semaphore(settings.max_inflight_requests)
    )
    try:
        await asyncio.wait_for(
            semaphore.acquire(), timeout=settings.load_shed_wait_seconds
        )
    except TimeoutError as failure:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The project knowledge service is busy. Please retry shortly.",
            headers={"Retry-After": "1"},
        ) from failure
    return semaphore


@app.middleware("http")
async def correlate_request(request: Request, call_next):
    correlation_id = new_request_id(request.headers.get("x-request-id"))
    token = set_request_id(correlation_id)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = correlation_id
        return response
    finally:
        reset_request_id(token)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/ready")
async def ready(settings: Settings = Depends(get_settings)) -> dict[str, str]:
    if not app.state.lexical_corpus_ready:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The lexical retrieval corpus is still warming.",
        )
    if not settings.llm_configured:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The configured LLM provider is incomplete.",
        )
    try:
        from chromadb import HttpClient

        await asyncio.to_thread(HttpClient(host=settings.chroma_host, port=settings.chroma_port).heartbeat)
        if settings.llm_provider == "ollama":
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(
                    f"{settings.ollama_base_url.rstrip('/')}/api/tags"
                )
                response.raise_for_status()
            if settings.local_models_path:
                if not Path(settings.local_models_path).expanduser().is_dir():
                    raise RuntimeError("The configured local reranker artifacts are unavailable.")
    except Exception as failure:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Chroma is unavailable or incorrectly configured.",
        ) from failure
    return {"status": "ok"}


@app.post(
    "/v1/answer",
    response_model=RagResponse,
    response_model_by_alias=True,
    dependencies=[Depends(require_internal_caller)],
)
async def answer(request: RagRequest, settings: Settings = Depends(get_settings)) -> RagResponse:
    """Return one verified RAG answer for non-streaming service consumers."""

    began = started()
    await app.state.project_rate_limiter.acquire(request.project_id)
    language = detect_query_language(request.question)
    required_project_policy = f"project:{request.project_id}"
    if required_project_policy not in request.access_policy_ids:
        refusal_began = started()
        refusal = no_access_answer(language)
        reason_code = "STATIC_FALLBACK"
        usage = None
        model_name = "none"
        try:
            responder = LangChainSafeResponseGenerator(settings, request.model_profile)
            refusal = await responder.generate(request.question, language, "NO_ACCESS")
            usage = responder.last_usage
            model_name = responder.model_name
            reason_code = "GENERATED_NO_ACCESS"
        except Exception:
            pass
        stage_complete(
            "generate_safe_response",
            request.project_id,
            refusal_began,
            input_count=1,
            output_count=1,
            reason_code=reason_code,
            model_provider=settings.llm_provider if usage is not None else "none",
            model_name=model_name,
            model_profile=request.model_profile,
            language=language,
            **(usage.model_dump() if usage is not None else {}),
        )
        request_complete(
            began=began,
            outcome="ACCESS_DENIED",
            confidence="NONE",
            model_profile=request.model_profile,
            language=language,
        )
        return RagResponse(
            answer=refusal,
            confidence="NONE",
            project_id=request.project_id,
            sources=[],
            missing_information=[],
        )
    if (
        request.embedding_model not in settings.supported_embedding_models
        or request.schema_version not in settings.supported_schema_versions
    ):
        stage_complete(
            "validate_schema",
            request.project_id,
            began,
            reason_code="INCOMPATIBLE_RETRIEVAL_SCHEMA",
            model_profile=request.model_profile,
            language=language,
        )
        request_complete(
            began=began,
            outcome="REJECTED",
            confidence="NONE",
            model_profile=request.model_profile,
            language=language,
        )
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The project retrieval schema is not compatible with this RAG deployment.",
        )
    request_slot = await _acquire_request_slot(settings)
    try:
        async with asyncio.timeout(settings.request_timeout_seconds):
            return await AuthorizedRagWorkflow(settings, request).run()
    except Exception as failure:
        failure_code = re.sub(r"[^A-Z0-9]+", "_", type(failure).__name__.upper()).strip("_")
        stage_complete(
            "pipeline_error",
            request.project_id,
            began,
            reason_code=failure_code or "UNKNOWN_ERROR",
            model_profile=request.model_profile,
            language=language,
        )
        request_complete(
            began=began,
            outcome="FAILED",
            confidence="NONE",
            model_profile=request.model_profile,
            language=language,
        )
        # The dependency or request budget has already failed. A second model
        # call would queue behind the same outage and delay the 503 again.
        user_message = pipeline_unavailable_answer(language)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, user_message) from failure
    finally:
        request_slot.release()


@app.post(
    "/v1/answer/stream",
    dependencies=[Depends(require_internal_caller)],
)
async def answer_stream(
    request: RagRequest,
    settings: Settings = Depends(get_settings),
) -> StreamingResponse:
    """Stream content-free graph progress followed by verified answer deltas."""

    began = started()
    await app.state.project_rate_limiter.acquire(request.project_id)

    required_project_policy = f"project:{request.project_id}"
    if required_project_policy not in request.access_policy_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Project access is required.")
    if (
        request.embedding_model not in settings.supported_embedding_models
        or request.schema_version not in settings.supported_schema_versions
    ):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The project retrieval schema is not compatible with this RAG deployment.",
        )

    request_slot = await _acquire_request_slot(settings)

    async def events():
        """Encode private-service stream events as newline-delimited JSON."""

        try:
            async with asyncio.timeout(settings.request_timeout_seconds):
                async for event in AuthorizedRagWorkflow(settings, request).stream():
                    yield json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        except Exception as failure:
            failure_code = re.sub(
                r"[^A-Z0-9]+", "_", type(failure).__name__.upper()
            ).strip("_") or "UNKNOWN_ERROR"
            LOGGER.exception(
                json.dumps(
                    {
                        "event": "rag_stream_failure",
                        "request_id": request_id(),
                        "project_id": request.project_id,
                        "exception_type": type(failure).__name__,
                        "exception_message": str(failure),
                        "reason_code": failure_code,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            request_complete(
                began=began,
                outcome="FAILED",
                confidence="NONE",
                model_profile=request.model_profile,
                language=detect_query_language(request.question),
                reason_code=failure_code,
            )
            language = detect_query_language(request.question)
            message = pipeline_unavailable_answer(language)
            yield json.dumps(
                {"type": "error", "message": message},
                ensure_ascii=False,
                separators=(",", ":"),
            ) + "\n"
        finally:
            request_slot.release()

    return StreamingResponse(
        events(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-store"},
    )
