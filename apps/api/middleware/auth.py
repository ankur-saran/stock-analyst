import asyncio
import time
from dataclasses import dataclass
from uuid import UUID

import httpx
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import ExpiredSignatureError, JWTError, jwt

from shared.config import Settings

settings = Settings()

ROLE_HIERARCHY: dict[str, int] = {
    "viewer": 0,
    "analyst": 1,
    "senior_analyst": 2,
    "admin": 3,
}

_jwks_cache: dict = {}
_jwks_lock = asyncio.Lock()
_JWKS_TTL = 300  # seconds

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id: UUID
    tenant_id: UUID
    role: str
    email: str


def _problem(status: int, detail: str) -> HTTPException:
    titles = {401: "Unauthorized", 403: "Forbidden"}
    return HTTPException(
        status_code=status,
        detail={
            "type": f"https://stockanalyst.ai/errors/{titles[status].lower()}",
            "title": titles[status],
            "status": status,
            "detail": detail,
        },
    )


async def _get_jwks() -> dict:
    now = time.monotonic()
    async with _jwks_lock:
        if _jwks_cache.get("expires_at", 0) > now:
            return _jwks_cache["keys"]
        url = (
            f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
            "/protocol/openid-connect/certs"
        )
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        keys = resp.json()
        _jwks_cache["keys"] = keys
        _jwks_cache["expires_at"] = now + _JWKS_TTL
        return keys


async def _decode_token(token: str) -> dict:
    """Decode and validate a Keycloak JWT. Raises jose.JWTError on any failure."""
    jwks = await _get_jwks()
    issuer = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}"
    return jwt.decode(
        token,
        jwks,
        algorithms=["RS256"],
        audience=settings.keycloak_client_id,
        issuer=issuer,
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    if credentials is None:
        raise _problem(401, "Bearer token is required")

    try:
        payload = await _decode_token(credentials.credentials)
    except ExpiredSignatureError:
        raise _problem(401, "Token has expired")
    except JWTError as exc:
        raise _problem(401, f"Invalid token: {exc}")

    raw_tenant_id = payload.get("tenant_id")
    if not raw_tenant_id:
        raise _problem(403, "Missing tenant_id claim in token")

    known_roles = [r for r in payload.get("realm_access", {}).get("roles", []) if r in ROLE_HIERARCHY]
    role = known_roles[0] if known_roles else "viewer"

    return CurrentUser(
        user_id=UUID(payload["sub"]),
        tenant_id=UUID(str(raw_tenant_id)),
        role=role,
        email=payload.get("email", ""),
    )


def role_required(minimum_role: str):
    """Dependency factory: raises 403 if user's role is below minimum_role."""
    min_level = ROLE_HIERARCHY.get(minimum_role, 0)

    async def _check(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if ROLE_HIERARCHY.get(user.role, 0) < min_level:
            raise _problem(403, f"Role '{minimum_role}' or higher required")
        return user

    return _check
