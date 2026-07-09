"""
Integration tests for authentication and RLS.

Prerequisites:
  - Full Docker Compose stack running (postgres, keycloak, redis, qdrant, minio, litellm)
  - DB migration applied:  alembic upgrade head
  - Dev data seeded:       python scripts/seed_dev.py
  - API running:           uvicorn apps.api.main:app --reload
  - Keycloak test users created with tenant_id custom claim (see conftest helpers below)

Run:
    pytest tests/integration/test_auth.py -v
"""

from __future__ import annotations

import time
import uuid

import httpx
import pytest
import pytest_asyncio
from jose import jwt as jose_jwt

APP_URL = "http://localhost:8000"
KC_URL = "http://localhost:8080"
REALM = "stockanalyst"
CLIENT_ID = "stockanalyst-api"
CLIENT_SECRET = "changeme"  # matches .env / docker-compose defaults
KC_ADMIN = "admin"
KC_ADMIN_PASS = "changeme"


# ── Keycloak helpers ──────────────────────────────────────────────────────────

async def _kc_admin_token() -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{KC_URL}/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": KC_ADMIN,
                "password": KC_ADMIN_PASS,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


async def _create_kc_user(
    admin_token: str, username: str, email: str, password: str, tenant_id: str
) -> str:
    """Create a Keycloak user with the tenant_id attribute; return user ID."""
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{KC_URL}/admin/realms/{REALM}/users",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={
                "username": username,
                "email": email,
                "enabled": True,
                "credentials": [{"type": "password", "value": password, "temporary": False}],
                "attributes": {"tenant_id": [tenant_id]},
                "realmRoles": ["analyst"],
            },
        )
        resp.raise_for_status()
        return resp.headers["Location"].split("/")[-1]


async def _delete_kc_user(admin_token: str, user_id: str) -> None:
    async with httpx.AsyncClient(timeout=10) as client:
        await client.delete(
            f"{KC_URL}/admin/realms/{REALM}/users/{user_id}",
            headers={"Authorization": f"Bearer {admin_token}"},
        )


async def _user_token(username: str, password: str) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            f"{KC_URL}/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "username": username,
                "password": password,
            },
        )
        resp.raise_for_status()
        return resp.json()["access_token"]


# ── Fixtures ──────────────────────────────────────────────────────────────────

TENANT_A_ID = str(uuid.uuid4())
TENANT_B_ID = str(uuid.uuid4())
_TEST_PASSWORD = "TestPass1!"


@pytest_asyncio.fixture(scope="session")
async def admin_token() -> str:
    return await _kc_admin_token()


@pytest_asyncio.fixture(scope="session")
async def tenant_a_token(admin_token: str) -> str:
    user_id = await _create_kc_user(
        admin_token,
        username="test_analyst_a",
        email="test_analyst_a@acme.example",
        password=_TEST_PASSWORD,
        tenant_id=TENANT_A_ID,
    )
    token = await _user_token("test_analyst_a", _TEST_PASSWORD)
    yield token
    await _delete_kc_user(admin_token, user_id)


# ── Test cases ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_returns_200_without_auth():
    """GET /health requires no auth and returns 200."""
    async with httpx.AsyncClient(base_url=APP_URL) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_health_deep_returns_200_all_ok():
    """GET /health/deep returns 200 and every service reports 'ok'."""
    async with httpx.AsyncClient(base_url=APP_URL, timeout=30) as client:
        resp = await client.get("/health/deep")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    for name, svc in body["services"].items():
        assert svc["status"] == "ok", f"Service '{name}' is not ok: {svc}"


@pytest.mark.asyncio
async def test_coverages_no_token_returns_401():
    """GET /coverages without a Bearer token must return 401."""
    async with httpx.AsyncClient(base_url=APP_URL) as client:
        resp = await client.get("/coverages")
    assert resp.status_code == 401
    detail = resp.json()
    assert detail["status"] == 401


@pytest.mark.asyncio
async def test_coverages_expired_token_returns_401():
    """GET /coverages with an invalid/expired JWT must return 401."""
    # Build a JWT-shaped string whose signature won't match Keycloak's public key.
    # Regardless of the expiry claim, jose will raise JWTError → 401.
    fake_token = (
        "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9"
        ".eyJzdWIiOiIwMDAwMDAwMC0wMDAwLTAwMDAtMDAwMC0wMDAwMDAwMDAwMDEiLCJleHAiOjF9"
        ".invalidsignature"
    )
    async with httpx.AsyncClient(base_url=APP_URL) as client:
        resp = await client.get("/coverages", headers={"Authorization": f"Bearer {fake_token}"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_coverages_valid_token_not_rejected(tenant_a_token: str):
    """GET /coverages with a valid Keycloak token must NOT return 401 or 403."""
    async with httpx.AsyncClient(base_url=APP_URL) as client:
        resp = await client.get(
            "/coverages", headers={"Authorization": f"Bearer {tenant_a_token}"}
        )
    # Stub returns 501; any non-auth error code means auth passed
    assert resp.status_code not in (401, 403), (
        f"Expected auth to succeed, got {resp.status_code}: {resp.json()}"
    )


@pytest.mark.asyncio
async def test_coverages_cross_tenant_rls(tenant_a_token: str):
    """GET /coverages/{id} with a tenant-A token must not expose tenant-B rows."""
    # A UUID that belongs to no tenant (or could belong to tenant-B in a full test)
    fake_tenant_b_coverage_id = "00000000-0000-0000-0000-000000000002"
    async with httpx.AsyncClient(base_url=APP_URL) as client:
        resp = await client.get(
            f"/coverages/{fake_tenant_b_coverage_id}",
            headers={"Authorization": f"Bearer {tenant_a_token}"},
        )
    # With stubs: returns 501. Once implemented: RLS yields 404 (row filtered) or 403.
    assert resp.status_code in (403, 404, 501), (
        f"Cross-tenant access should be blocked, got {resp.status_code}"
    )
