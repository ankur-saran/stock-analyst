"""Fixtures for tests/e2e/.

pytest-playwright's own ``page``/``browser``/``context`` fixtures are
sync-only (they wrap ``playwright.sync_api``); the rest of this suite is
async, so this file builds the same fixtures on top of
``playwright.async_api`` instead of adding that plugin.

Every test under tests/e2e/ is collected but skipped unless ``--e2e`` is
passed (see tests/conftest.py's ``pytest_collection_modifyitems``) -- running
them for real needs the full stack (Next.js app on :3000, the API, Keycloak)
reachable, plus a one-time ``playwright install chromium``.
"""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio

E2E_BASE_URL = os.environ.get("E2E_BASE_URL", "http://localhost:3000")

# infra/keycloak/realm-export.json's pre-seeded tenant-A analyst. The
# Keycloak login form's username field wants the bare username, not the
# email attribute -- confirmed against a real login by _run_login_flow.mjs
# at the repo root.
_TENANT_A_USERNAME = "analyst-a"
_TEST_PASSWORD = "TestPass123!"


@pytest_asyncio.fixture
async def browser() -> AsyncIterator[object]:
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest_asyncio.fixture
async def context(browser) -> AsyncIterator[object]:
    ctx = await browser.new_context(viewport={"width": 1366, "height": 900})
    yield ctx
    await ctx.close()


@pytest_asyncio.fixture
async def page(context) -> AsyncIterator[object]:
    pg = await context.new_page()
    yield pg
    await pg.close()


@pytest_asyncio.fixture
async def logged_in_page(page) -> object:
    """``page``, already authenticated as the pre-seeded tenant-A analyst.

    Mirrors the flow _run_login_flow.mjs verified working: hit a protected
    route, follow the app's "Sign in with your organization" button into
    Keycloak, fill the login form, and land back on the app.
    """
    await page.goto(f"{E2E_BASE_URL}/coverages", wait_until="networkidle", timeout=60_000)
    await page.get_by_role("button", name="Sign in with your organization").click(timeout=15_000)
    await page.wait_for_selector("#username", timeout=30_000)
    await page.fill("#username", _TENANT_A_USERNAME)
    await page.fill("#password", _TEST_PASSWORD)
    await page.click("#kc-login")
    await page.wait_for_url(f"{E2E_BASE_URL}/**", timeout=60_000)
    await page.wait_for_load_state("networkidle", timeout=60_000)
    return page
