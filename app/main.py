import asyncio
from contextlib import asynccontextmanager
from contextlib import suppress
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
from app.models import AnswerStatus, Coverage, RagRequest, RagResponse
from app.openinference_tracing import configure_openinference
from app.embedding import build_embedder, warm_embedder
from app.reranking import build_reranker
from app.retrieval import warm_authorized_lexical_corpora
from app.security import ProjectRateLimiter, RequestSizeLimitMiddleware, SecurityHeadersMiddleware
from app.security import require_internal_caller
from app.workflow import AuthorizedRagWorkflow
from app.workflow_support.language import resolve_response_language
from app.telemetry import (
    configure_telemetry_logging,
    new_request_id,
    admission_capacity,
    request_complete,
    request_admitted,
    request_id,
    request_released,
    reset_request_id,
    request_shed,
    set_request_id,
    stage_complete,
    started,
)


def _cancellation_requested() -> bool:
    """True when this task has been asked to stop.

    `asyncio.wait_for` can surface an external cancellation as TimeoutError, and
    a retry loop that treats every TimeoutError as "try again" then ignores the
    request and runs forever -- a process alive and stuck on shutdown, which is
    the same failure this module was rewritten to remove from startup.
    """

    task = asyncio.current_task()
    return task is not None and task.cancelling() > 0


async def _warm_lexical_corpora_until_ready(
    application: FastAPI, settings: Settings, embedder: object
) -> None:
    """Warm the optional lexical cache without holding the ASGI lifespan open."""

    while not application.state.lexical_corpus_ready:
        try:
            await asyncio.wait_for(
                warm_authorized_lexical_corpora(settings, embedder),
                timeout=settings.lexical_corpus_warm_timeout_seconds,
            )
            application.state.lexical_corpus_ready = True
            logging.getLogger("app.startup").info(
                "The authorized lexical corpora are warm; RAG is ready."
            )
            return
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            if _cancellation_requested():
                raise asyncio.CancelledError
            logging.getLogger("app.startup").warning(
                "The lexical corpus warm-up exceeded %.1fs; serving with the "
                "corpus cold and retrying in %.1fs. Chroma at %s:%s is the "
                "usual cause.",
                settings.lexical_corpus_warm_timeout_seconds,
                settings.lexical_corpus_warm_retry_seconds,
                settings.chroma_host,
                settings.chroma_port,
            )
        except Exception as failure:
            if _cancellation_requested():
                raise asyncio.CancelledError
            logging.getLogger("app.startup").warning(
                "The lexical corpus warm-up failed (%s: %s); serving with the "
                "corpus cold and retrying in %.1fs. Chroma at %s:%s is the "
                "usual cause.",
                type(failure).__name__,
                failure,
                settings.lexical_corpus_warm_retry_seconds,
                settings.chroma_host,
                settings.chroma_port,
            )
        await asyncio.sleep(settings.lexical_corpus_warm_retry_seconds)


async def _warm_or_report(name: str, awaitable) -> None:
    """Run a startup warm-up, downgrading any failure to a log line."""

    try:
        await awaitable
    except asyncio.CancelledError:
        raise
    except Exception as failure:
        logging.getLogger("app.startup").warning(
            "The %s warm-up failed (%s: %s); serving cold. /ready stays 503 "
            "while its dependency is unavailable.",
            name,
            type(failure).__name__,
            failure,
        )


@asynccontextmanager
async def lifespan(_application: FastAPI):
    """Warm local models and recover optional caches without blocking liveness."""

    settings = get_settings()
    tracer_provider = configure_openinference(settings)
    _application.state.lexical_corpus_ready = not (
        settings.lexical_fallback_enabled
        and settings.warm_lexical_corpus_on_startup
    )
    if settings.warm_local_models_on_startup:
        reranker = build_reranker(settings)
        # Warming is an optimisation, never a precondition. When scoring is
        # delegated to the accelerator this is a call to another process, and
        # letting it raise here would make the container exit and -- under
        # `restart: unless-stopped` -- crash-loop for as long as that worker is
        # down. /ready already reports the accelerator, so the honest behaviour
        # is to serve, stay unready, and recover on its own.
        await _warm_or_report(
            "reranker",
            reranker.rerank(
                "project knowledge",
                [
                    Document(
                        page_content="Project knowledge warm-up sample.",
                        metadata={"source_id": "startup-warmup", "score": 1.0},
                    )
                ],
                score_threshold=0.0,
                top_n=1,
            ),
        )
    embedder = build_embedder(settings)
    if settings.warm_local_embedder_on_startup:
        # to_thread because warm_embedder is synchronous and, against the
        # accelerator, performs a blocking socket read. On the event loop it
        # stalls everything else in startup, including liveness.
        await _warm_or_report(
            "embedder", asyncio.to_thread(warm_embedder, embedder)
        )
    warm_task = None
    if settings.lexical_fallback_enabled and settings.warm_lexical_corpus_on_startup:
        # Never await a downstream from inside startup. The ASGI server can expose
        # /health immediately, while /ready remains 503 until this task succeeds.
        # If Chroma comes back later, the task retries and readiness self-recovers.
        warm_task = asyncio.create_task(
            _warm_lexical_corpora_until_ready(_application, settings, embedder),
            name="warm-authorized-lexical-corpora",
        )
    try:
        yield
    finally:
        if warm_task is not None:
            warm_task.cancel()
            # Bounded on purpose. Shutdown must complete even if this task finds
            # another way to lose its cancellation; a stuck shutdown is as bad
            # as a stuck startup.
            with suppress(asyncio.CancelledError, TimeoutError):
                await asyncio.wait_for(warm_task, timeout=5)
        if tracer_provider is not None:
            await asyncio.to_thread(tracer_provider.shutdown)


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


class _RequestSlot:
    def __init__(self, semaphore: asyncio.Semaphore) -> None:
        self._semaphore = semaphore
        self._released = False

    def release(self) -> None:
        if self._released:
            return
        self._released = True
        self._semaphore.release()
        request_released()


async def _acquire_request_slot(settings: Settings) -> _RequestSlot:
    """Acquire capacity before retrieval or reject the request immediately."""

    loop = asyncio.get_running_loop()
    # Every locally served request uses the shared MPS reranker, and local model
    # generation is bounded by the same configured capacity. Admitting a wider
    # request window only moves the queue inside expensive stages, where requests
    # compete for unified memory and turn normal seconds into minute-long tail
    # latency. Shed excess work at the request boundary instead.
    capacity = settings.max_inflight_requests
    if settings.local_inference_enabled:
        capacity = min(capacity, settings.local_max_concurrency)
    key = (id(loop), capacity)
    if key not in _REQUEST_SEMAPHORES:
        _REQUEST_SEMAPHORES[key] = asyncio.Semaphore(capacity)
        admission_capacity(capacity)
        if capacity < settings.max_inflight_requests:
            LOGGER.info(
                "Admission capacity is %d, clamped from PI_RAG_MAX_INFLIGHT_"
                "REQUESTS=%d by PI_RAG_LOCAL_MAX_CONCURRENCY=%d. Requests beyond "
                "it are shed with 503, not queued.",
                capacity,
                settings.max_inflight_requests,
                settings.local_max_concurrency,
            )
    semaphore = _REQUEST_SEMAPHORES[key]
    admission_began = started()
    try:
        await asyncio.wait_for(
            semaphore.acquire(), timeout=settings.load_shed_wait_seconds
        )
    except TimeoutError as failure:
        request_shed(admission_began)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The project knowledge service is busy. Please retry shortly.",
            headers={"Retry-After": "1"},
        ) from failure
    request_admitted(admission_began)
    return _RequestSlot(semaphore)


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
        if settings.local_accelerator_url:
            from app.accelerator import accelerator_request

            await asyncio.to_thread(
                accelerator_request,
                settings.local_accelerator_url,
                "/health",
                None,
                api_key=settings.internal_api_key,
                timeout_seconds=5,
            )
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
    language = resolve_response_language(
        request.question, default=settings.default_response_language
    )
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
            status=AnswerStatus.ACCESS_DENIED,
            answer=refusal,
            confidence="NONE",
            project_id=request.project_id,
            sources=[],
            missing_information=[],
            coverage=Coverage.NOT_APPLICABLE,
            failureReason="ACCESS_DENIED",
            resolvedIntent="ACCESS_CHECK",
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
                language=resolve_response_language(request.question),
                reason_code=failure_code,
            )
            language = resolve_response_language(request.question)
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
