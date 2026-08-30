import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

KEY_ID = "forge-local-key-1"


class DevIssuer:
    def __init__(self, issuer: str, audience: str, jwks_path: Path) -> None:
        self.issuer = issuer
        self.audience = audience
        self.jwks_path = jwks_path
        self.private_key_path = jwks_path.parent / "private-key.pem"

    def ensure_keys(self) -> None:
        self.jwks_path.parent.mkdir(parents=True, exist_ok=True)
        if self.private_key_path.exists() and self.jwks_path.exists():
            return
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        private_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        self.private_key_path.write_bytes(private_pem)
        public_jwk = json.loads(
            jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key(), as_dict=False)
        )
        public_jwk.update({"kid": KEY_ID, "use": "sig", "alg": "RS256"})
        self.jwks_path.write_text(json.dumps({"keys": [public_jwk]}, indent=2))

    def token_for_subject(
        self,
        *,
        subject: str,
        email: str,
        name: str,
        ttl_seconds: int = 3600,
        overrides: dict[str, Any] | None = None,
    ) -> str:
        self.ensure_keys()
        private_key = cast(
            rsa.RSAPrivateKey,
            serialization.load_pem_private_key(
                self.private_key_path.read_bytes(),
                password=None,
            ),
        )
        now = datetime.now(tz=UTC)
        claims: dict[str, Any] = {
            "iss": self.issuer,
            "aud": self.audience,
            "sub": subject,
            "email": email,
            "name": name,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int((now + timedelta(seconds=ttl_seconds)).timestamp()),
        }
        if overrides:
            claims.update(overrides)
        return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": KEY_ID})
