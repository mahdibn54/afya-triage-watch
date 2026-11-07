"""E13-3 test fixture: a local RSA key pair stands in for the authorization server, so the tests sign their own
RFC 9068 access tokens and need no network and no running Authelia. conftest.py points afya_mcp.auth at it."""
from __future__ import annotations

import time
import uuid

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "https://auth.test"
BASE = "http://afya-mcp:9000"
SCOPES = {"read": "afya:read", "act": "afya:act", "ui": "afya:ui"}
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)   # not the issuer's: bad signature


class LocalKeys:
    """Stands in for IssuerKeys: the issuer's public key, whatever the token says."""

    async def key(self, _token: str):
        return KEY.public_key()


def mint(mount: str = "read", *, scope: str | list[str] | None = None, aud: str | list[str] | None = None,
         iss: str = ISSUER, expires_in: int = 300, key=KEY, typ: str = "at+jwt", alg: str = "RS256",
         drop: tuple[str, ...] = (), **extra) -> str:
    """A signed access token for `mount`, by default valid (issuer, audience = the mount's resource, its scope)."""
    now = int(time.time())
    claims = {"iss": iss, "sub": "afya-api", "client_id": "afya-api", "aud": aud or [f"{BASE}/{mount}/mcp"],
              "iat": now, "nbf": now, "exp": now + expires_in, "jti": str(uuid.uuid4())}
    scope = SCOPES[mount] if scope is None else scope
    if isinstance(scope, list):
        claims["scp"] = scope          # Authelia's form
    else:
        claims["scope"] = scope        # RFC 9068's form
    claims.update(extra)
    for name in drop:
        claims.pop(name, None)
    return jwt.encode(claims, key, algorithm=alg, headers={"typ": typ, "kid": "test-1"})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
