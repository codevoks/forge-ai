import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


class LocalRateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, limit: int = 30, window_seconds: int = 60) -> None:
        super().__init__(app)
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.url.path.startswith(("/dev/oidc/token", "/v1/tenants")):
            key = f"{request.client.host if request.client else 'unknown'}:{request.url.path}"
            now = time.monotonic()
            hits = self._hits[key]
            while hits and now - hits[0] > self.window_seconds:
                hits.popleft()
            if len(hits) >= self.limit:
                return JSONResponse(
                    status_code=429,
                    content={
                        "code": "rate_limited",
                        "message": "Too many requests.",
                        "correlation_id": request.headers.get("x-correlation-id", "rate-limit"),
                        "retryable": True,
                    },
                )
            hits.append(now)
        return await call_next(request)
