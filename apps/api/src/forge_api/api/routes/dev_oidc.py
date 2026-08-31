from typing import Annotated

from fastapi import APIRouter, Depends

from forge_api.api.dependencies import get_settings
from forge_api.config import Settings
from forge_api.infrastructure.dev_issuer import DevIssuer

router = APIRouter(prefix="/dev/oidc", tags=["development identity"])


@router.get("/token/{subject}")
def token(subject: str, settings: Annotated[Settings, Depends(get_settings)]) -> dict[str, str]:
    settings.assert_zero_cost_safe()
    subjects = {
        "alice": ("oidc|alice", "alice@forge.local", "Alice Admin"),
        "ava": ("oidc|ava", "ava@forge.local", "Ava Approver"),
        "bob": ("oidc|bob", "bob@forge.local", "Bob Viewer"),
        "mallory": ("oidc|mallory", "mallory@forge.local", "Mallory Outsider"),
    }
    sub, email, name = subjects.get(subject, (f"oidc|{subject}", f"{subject}@forge.local", subject))
    issuer = DevIssuer(settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_path)
    return {"access_token": issuer.token_for_subject(subject=sub, email=email, name=name)}
