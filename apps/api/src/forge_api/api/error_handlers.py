from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from forge_api.api.errors import ProblemError


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ProblemError)
    async def problem_handler(request: Request, exc: ProblemError) -> JSONResponse:
        correlation_id = request.headers.get("x-correlation-id", str(uuid4()))
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "code": exc.code,
                "message": exc.message,
                "correlation_id": correlation_id,
                "retryable": exc.retryable,
            },
        )
