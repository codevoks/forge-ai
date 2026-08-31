from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from forge_api.api.error_handlers import install_error_handlers
from forge_api.api.rate_limit import LocalRateLimitMiddleware
from forge_api.api.routes import (
    agents,
    approvals,
    dev_oidc,
    health,
    identity,
    operations,
    planning,
    runs,
    tenants,
    tools,
    workflows,
    workspaces,
)
from forge_api.config import Settings


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(
        title="Forge AI API",
        version="0.1.0",
        docs_url="/docs" if settings.environment == "development" else None,
        redoc_url=None,
    )
    app.state.settings = settings
    app.add_middleware(LocalRateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://127.0.0.1:3000", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "If-Match"],
    )
    install_error_handlers(app)
    app.include_router(agents.router)
    app.include_router(health.router)
    app.include_router(dev_oidc.router)
    app.include_router(identity.router)
    app.include_router(operations.router)
    app.include_router(tenants.router)
    app.include_router(approvals.router)
    app.include_router(tools.router)
    app.include_router(workspaces.router)
    app.include_router(workflows.router)
    app.include_router(runs.router)
    app.include_router(planning.router)
    return app
