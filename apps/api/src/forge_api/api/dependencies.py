from typing import Annotated

from fastapi import Depends, Header, Request

from forge_api.api.errors import ProblemError
from forge_api.application.identity_service import IdentityService
from forge_api.config import Settings
from forge_api.domain.identity import ActorContext
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.oidc import LocalJwksIdentityProvider
from forge_api.ports.telemetry import TelemetryPort


def get_settings(request: Request) -> Settings:
    settings = request.app.state.settings
    if not isinstance(settings, Settings):
        raise ProblemError(500, "settings_unavailable", "Application settings are unavailable.")
    return settings


def get_database(settings: Annotated[Settings, Depends(get_settings)]) -> Database:
    return Database(settings.database_url)


def get_telemetry(request: Request) -> TelemetryPort:
    telemetry = request.app.state.telemetry
    if telemetry is None:
        raise ProblemError(500, "telemetry_unavailable", "Application telemetry is unavailable.")
    telemetry_port: TelemetryPort = telemetry
    return telemetry_port


def get_identity_provider(
    settings: Annotated[Settings, Depends(get_settings)],
) -> LocalJwksIdentityProvider:
    return LocalJwksIdentityProvider(settings)


def parse_bearer(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise ProblemError(401, "auth_required", "A bearer access token is required.")
    return authorization.removeprefix("Bearer ").strip()


def require_idempotency_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
    if not idempotency_key or len(idempotency_key) > 128:
        raise ProblemError(
            400,
            "idempotency_key_required",
            "A valid Idempotency-Key header is required.",
        )
    return idempotency_key


def require_if_match(if_match: Annotated[str | None, Header()] = None) -> int:
    if not if_match:
        raise ProblemError(428, "if_match_required", "If-Match version header is required.")
    try:
        version = int(if_match.strip().strip('"'))
    except ValueError as exc:
        raise ProblemError(400, "if_match_invalid", "If-Match must be a resource version.") from exc
    if version < 1:
        raise ProblemError(400, "if_match_invalid", "If-Match must be a positive version.")
    return version


def get_actor(
    authorization: Annotated[str | None, Header()] = None,
    identity_provider: Annotated[
        LocalJwksIdentityProvider | None,
        Depends(get_identity_provider),
    ] = None,
    database: Annotated[Database | None, Depends(get_database)] = None,
) -> ActorContext:
    if identity_provider is None or database is None:
        raise ProblemError(500, "dependency_error", "Identity dependencies are unavailable.")
    claims = identity_provider.verify(parse_bearer(authorization))
    return IdentityService(database).actor_from_claims(claims)
