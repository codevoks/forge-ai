from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from forge_api.config import Settings
from forge_api.infrastructure.database import Database
from forge_api.infrastructure.dev_issuer import DevIssuer
from forge_api.main import create_app
from forge_api.scripts.migrate import main as migrate_main
from forge_api.scripts.seed import main as seed_main


@pytest.fixture(scope="session", autouse=True)
def migrated_database() -> Iterator[None]:
    migrate_main()
    seed_main()
    yield


@pytest.fixture
def settings() -> Settings:
    return Settings()


@pytest.fixture
def database(settings: Settings) -> Database:
    return Database(settings.database_url)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


@pytest.fixture
def issuer(settings: Settings) -> DevIssuer:
    return DevIssuer(settings.oidc_issuer, settings.oidc_audience, settings.oidc_jwks_path)


def auth_headers(issuer: DevIssuer, subject: str) -> dict[str, str]:
    subjects = {
        "alice": ("oidc|alice", "alice@forge.local", "Alice Admin"),
        "ava": ("oidc|ava", "ava@forge.local", "Ava Approver"),
        "bob": ("oidc|bob", "bob@forge.local", "Bob Viewer"),
        "mallory": ("oidc|mallory", "mallory@forge.local", "Mallory Outsider"),
    }
    sub, email, name = subjects[subject]
    token = issuer.token_for_subject(subject=sub, email=email, name=name)
    return {"Authorization": f"Bearer {token}"}
