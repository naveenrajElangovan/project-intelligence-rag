import asyncio
from collections import defaultdict, deque
import hmac
import time
from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp, Message, Receive, Scope, Send
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.config import Settings, get_settings


class RequestSizeLimitMiddleware:
    """Enforce the body cap on received bytes, including chunked requests."""

    def __init__(self, app: ASGIApp, maximum_bytes: int) -> None:
        self.app = app
        self._maximum_bytes = maximum_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        received = 0
        messages: list[Message] = []
        while True:
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self._maximum_bytes:
                    response = JSONResponse(
                        {"detail": "Request body is too large."}, status_code=413
                    )
                    await response(scope, receive, send)
                    return
            messages.append(message)
            if message["type"] != "http.request" or not message.get(
                "more_body", False
            ):
                break

        async def replay() -> Message:
            if messages:
                return messages.pop(0)
            return await receive()

        await self.app(scope, replay, send)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, hsts: bool = False) -> None:
        super().__init__(app)
        self._hsts = hsts

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
        if self._hsts:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


class ProjectRateLimiter:
    """Per-replica project backstop; ingress remains the distributed limiter."""

    def __init__(self, requests_per_minute: int) -> None:
        self._limit = requests_per_minute
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def acquire(self, project_id: str) -> None:
        now = time.monotonic()
        async with self._lock:
            for identity, values in list(self._requests.items()):
                while values and values[0] <= now - 60:
                    values.popleft()
                if not values:
                    del self._requests[identity]
            values = self._requests[project_id]
            if len(values) >= self._limit:
                raise HTTPException(
                    status_code=429,
                    detail="RAG request rate limit exceeded.",
                    headers={"Retry-After": "60"},
                )
            values.append(now)


async def require_internal_caller(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    expected = settings.internal_api_key
    if not expected and settings.environment.strip().lower() == "development":
        return
    if (
        not expected
        or not authorization
        or not authorization.startswith("Bearer ")
        or not hmac.compare_digest(authorization[7:], expected)
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid internal service credential.",
            headers={"WWW-Authenticate": "Bearer"},
        )
