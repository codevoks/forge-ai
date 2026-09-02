import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from forge_api.api.errors import ProblemError
from forge_api.config import Settings


class LocalJwksIdentityProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def verify(self, token: str) -> dict[str, Any]:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.InvalidTokenError as exc:
            raise ProblemError(401, "invalid_token", "The access token is not valid.") from exc

        if header.get("alg") != "RS256":
            raise ProblemError(
                401,
                "invalid_token_algorithm",
                "The access token algorithm is not allowed.",
            )

        key = self._key_for_kid(str(header.get("kid", "")))
        try:
            decoded = jwt.decode(
                token,
                key=key,
                algorithms=["RS256"],
                audience=self.settings.oidc_audience,
                issuer=self.settings.oidc_issuer,
                options={"require": ["exp", "iat", "nbf", "iss", "aud", "sub"]},
                leeway=5,
            )
            return decoded
        except jwt.ExpiredSignatureError as exc:
            raise ProblemError(401, "token_expired", "The access token has expired.") from exc
        except jwt.InvalidTokenError as exc:
            raise ProblemError(401, "invalid_token", "The access token is not valid.") from exc

    def _key_for_kid(self, kid: str) -> Any:
        jwks_path = Path(self.settings.oidc_jwks_path)
        if not jwks_path.exists():
            raise ProblemError(
                503,
                "jwks_unavailable",
                "The identity key set is unavailable.",
                True,
            )
        jwks = json.loads(jwks_path.read_text())
        for key in jwks.get("keys", []):
            if key.get("kid") == kid and key.get("kty") == "RSA":
                return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key))
        raise ProblemError(401, "unknown_key", "The access token signing key is not trusted.")


def now_epoch() -> int:
    return int(datetime.now(tz=UTC).timestamp())


def generate_rsa_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)
