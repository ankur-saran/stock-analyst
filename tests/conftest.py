"""Shared pytest fixtures for the whole tests/ suite.

Kept free of any project-code imports at module level (only stdlib,
pytest/pytest_asyncio, and httpx) so that ``pytest tests/unit/`` collects and
runs with no Postgres/Qdrant/Keycloak stack available -- every fixture that
needs ``shared``, ``rag``, ``agents``, or ``apps.api`` imports it inside the
fixture body instead, where it's only ever executed by a test that actually
requested that fixture.
"""
from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio

# ── Well-known identifiers ───────────────────────────────────────────────────
# Match scripts/seed_dev.py ("Acme Capital" / "Beta Fund") and the pre-seeded
# Keycloak users in infra/keycloak/realm-export.json (analyst-a / analyst-b,
# both password TestPass123!) -- no per-session user create/delete needed,
# unlike tests/integration/test_auth.py's dynamic-user approach.
TEST_TENANT_A_ID = "00000000-0000-0000-0000-000000000001"  # "Acme Capital"
TEST_TENANT_B_ID = "00000000-0000-0000-0000-000000000002"  # "Beta Fund"

_TEST_PASSWORD = "TestPass123!"
_TENANT_A_USERNAME = "analyst-a"
_TENANT_B_USERNAME = "analyst-b"


# ── CLI option: --e2e gates tests/e2e/ (needs the full stack + a browser) ───


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--e2e",
        action="store_true",
        default=False,
        help="Run tests marked e2e (requires the API, the Next.js app, Keycloak, "
        "and a Chromium browser via `playwright install chromium`).",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--e2e"):
        return
    skip_e2e = pytest.mark.skip(reason="e2e test -- pass --e2e to run it against a live stack")
    for item in items:
        if "e2e" in item.keywords:
            item.add_marker(skip_e2e)


# ── Tenant identifiers ───────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def test_tenant_a_id() -> str:
    return TEST_TENANT_A_ID


@pytest.fixture(scope="session")
def test_tenant_b_id() -> str:
    return TEST_TENANT_B_ID


# ── Live API base URL ────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def api_base_url() -> str:
    return os.environ.get("API_BASE_URL", "http://localhost:8000")


# ── Keycloak-minted JWTs for the two pre-seeded tenant users ────────────────


async def _password_grant_token(username: str, password: str) -> str:
    from shared.config import Settings

    settings = Settings()
    token_url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": settings.keycloak_client_id,
                "client_secret": settings.keycloak_client_secret.get_secret_value(),
                "username": username,
                "password": password,
            },
        )
        resp.raise_for_status()
        return str(resp.json()["access_token"])


@pytest_asyncio.fixture(scope="session")
async def tenant_a_jwt() -> str:
    return await _password_grant_token(_TENANT_A_USERNAME, _TEST_PASSWORD)


@pytest_asyncio.fixture(scope="session")
async def tenant_b_jwt() -> str:
    return await _password_grant_token(_TENANT_B_USERNAME, _TEST_PASSWORD)


# ── Authenticated API clients ────────────────────────────────────────────────


@pytest_asyncio.fixture
async def api_client_tenant_a(api_base_url: str, tenant_a_jwt: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=api_base_url, headers={"Authorization": f"Bearer {tenant_a_jwt}"}, timeout=30.0
    ) as client:
        yield client


@pytest_asyncio.fixture
async def api_client_tenant_b(api_base_url: str, tenant_b_jwt: str) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        base_url=api_base_url, headers={"Authorization": f"Bearer {tenant_b_jwt}"}, timeout=30.0
    ) as client:
        yield client


@pytest.fixture
def api_client(api_client_tenant_a: httpx.AsyncClient) -> httpx.AsyncClient:
    """Alias for the common single-tenant case: tenant A's client."""
    return api_client_tenant_a


@pytest_asyncio.fixture
async def tenant_a_coverage_id(api_client_tenant_a: httpx.AsyncClient) -> str:
    """A coverage owned by tenant A, created fresh for whichever test asks for it.

    Not cleaned up afterwards: ``DELETE /coverages/{id}`` is still a 501 stub
    (apps/api/routers/coverages.py), so there is no API-level teardown path.
    That's fine for a Docker Compose stack that gets ``down -v``'d between CI
    runs, but means repeated local runs will accumulate test coverages.
    """
    resp = await api_client_tenant_a.post(
        "/coverages",
        json={
            "ticker": f"TSTA{uuid.uuid4().hex[:5].upper()}",
            "company_name": "Tenant Isolation Test Co (A)",
            "exchange": "NASDAQ",
        },
    )
    resp.raise_for_status()
    return str(resp.json()["id"])


@pytest_asyncio.fixture
async def tenant_b_coverage_id(api_client_tenant_b: httpx.AsyncClient) -> str:
    """Same as ``tenant_a_coverage_id`` but owned by tenant B -- used to prove
    tenant A's DB session/RLS context genuinely can't see it, rather than the
    weaker (and vacuous if tenant B simply has zero coverages) check of just
    counting pre-existing rows.
    """
    resp = await api_client_tenant_b.post(
        "/coverages",
        json={
            "ticker": f"TSTB{uuid.uuid4().hex[:5].upper()}",
            "company_name": "Tenant Isolation Test Co (B)",
            "exchange": "NASDAQ",
        },
    )
    resp.raise_for_status()
    return str(resp.json()["id"])


# ── Database session (direct RLS assertions) ─────────────────────────────────


@pytest_asyncio.fixture(scope="session")
async def db_engine() -> AsyncIterator[Any]:
    from shared.config import Settings
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(Settings().get_db_url(), pool_pre_ping=True)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine: Any, test_tenant_a_id: str) -> AsyncIterator[Any]:
    """An AsyncSession scoped to tenant A by default (mirrors
    apps/api/db.py's ``get_db``, but session-scoped rather than
    transaction-local since a test may issue several separate statements).
    Individual tests are free to re-run ``set_config`` to switch tenant
    context mid-test (see tests/integration/test_tenant_isolation.py).
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession

    async with AsyncSession(db_engine, expire_on_commit=False) as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tid, false)"),
            {"tid": test_tenant_a_id},
        )
        yield session
        await session.rollback()


# ── LLM response mocking ──────────────────────────────────────────────────────


@pytest.fixture
def mock_llm_response() -> Callable[..., tuple[str, str, int]]:
    """Factory matching ``BaseAgent._call_llm``'s real return contract: a
    plain ``(content, model, tokens)`` tuple (see
    packages/agents/src/agents/shared/base_agent.py) -- not an OpenAI-style
    response object. Use it with e.g.::

        monkeypatch.setattr(
            SomeAgent, "_call_llm",
            AsyncMock(return_value=mock_llm_response("...")),
        )

    the same pattern tests/unit/test_orchestrator_agent.py and
    tests/unit/test_lynch_pitch_agent.py already use.
    """

    def factory(content: str, model: str = "claude-sonnet-4-6", tokens: int = 500) -> tuple[str, str, int]:
        return content, model, tokens

    return factory


# ── Retriever mocking ─────────────────────────────────────────────────────────


@pytest.fixture
def mock_retriever() -> Any:
    """AsyncMock standing in for HybridRetriever, pre-loaded with a handful of
    synthetic AAPL 10-K chunks so agent/enforcer unit tests don't need Qdrant.
    """
    from unittest.mock import AsyncMock

    from rag.retrieval.hybrid_retriever import RetrievedChunk

    retriever = AsyncMock()

    def make_chunk(
        content: str,
        doc_name: str = "AAPL 10-K 2023",
        section: str = "Business",
        chunk_id: str | None = None,
    ) -> RetrievedChunk:
        return RetrievedChunk(
            chunk_id=chunk_id or str(uuid.uuid4()),
            content=content,
            metadata={
                "document_name": doc_name,
                "section_name": section,
                "tenant_id": TEST_TENANT_A_ID,
                "coverage_id": "test-coverage-id",
                "page_number": 1,
                "filing_type": "10-K",
                "period": "FY2023",
            },
            score=0.92,
            parent_content=f"[Parent context for: {content[:50]}]",
            parent_chunk_id=str(uuid.uuid4()),
        )

    retriever.retrieve.return_value = [
        make_chunk("Revenue was $383.3 billion for fiscal year 2023"),
        make_chunk("Gross margin was 44.1%, up from 43.3% in fiscal 2022"),
        make_chunk("The Company had $29.9 billion in cash and marketable securities"),
    ]
    retriever.retrieve_exact_quote.return_value = make_chunk(
        "Revenue was $383.3 billion for fiscal year 2023"
    )
    # No dense-similarity hit by default -- tests exercising the
    # CitationEnforcer's paraphrase-detection fallback (see
    # packages/agents/shared/citation_enforcer.py) should override this
    # per-test with `retriever.retrieve_semantic_quote.return_value = ...`.
    retriever.retrieve_semantic_quote.return_value = None
    retriever.make_chunk = make_chunk  # helper for building custom test data
    return retriever
