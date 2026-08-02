"""E2E flows through the real Next.js app + API + Keycloak, driven by
Playwright's async API.

Skipped by default. Run with:
    pytest tests/e2e/ -v --e2e
against a fully running stack:
    make up && alembic upgrade head && make seed && make pull-model
    make dev-api    # separate terminal
    make dev-web    # separate terminal
    pip install -r tests/e2e/requirements.txt && playwright install chromium
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.e2e, pytest.mark.asyncio]

# A small synthetic eval fixture (see eval/fixtures/fixture_content.py) --
# shaped like a 10-K so the ingestion pipeline's section detection exercises
# the same code path a real filing would.
_FIXTURE_PDF = Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "documents" / "newco_10k_2023.pdf"


async def _create_coverage(page, *, ticker: str, company_name: str) -> None:
    """New-coverage flow shared by both tests below.

    Exchange is a Radix/shadcn <Select>, not a native <select> -- there is no
    `<select name="exchange">` to target with `select_option` (see
    apps/web/components/coverages/new-coverage-sheet.tsx), so this opens the
    combobox and clicks the rendered option text instead. Exchange is the
    first of the sheet's two comboboxes (Industry is the second).
    """
    await page.get_by_role("button", name="New Coverage").click()
    await page.locator("#ticker").fill(ticker)
    await page.locator("#company-name").fill(company_name)
    await page.get_by_role("combobox").nth(0).click()
    await page.get_by_role("option", name="NASDAQ", exact=True).click()
    await page.get_by_role("button", name="Create Coverage").click()
    await page.wait_for_url("**/coverages/**/documents", timeout=30_000)


async def test_analyst_login_and_coverage_creation(logged_in_page) -> None:
    page = logged_in_page
    assert "/login" not in page.url

    await _create_coverage(page, ticker="NVDA", company_name="NVIDIA Corporation")

    assert "documents" in page.url


async def test_document_upload_and_ingestion_status(logged_in_page) -> None:
    page = logged_in_page
    await _create_coverage(page, ticker="UPLD", company_name="Upload Flow Test Co")

    await page.get_by_role("button", name="Upload Document").click()
    # react-dropzone renders a plain (visually hidden) <input type="file">
    # with no id/name/data-testid; set_input_files works on it regardless of
    # visibility since it operates on the DOM element directly.
    await page.locator('input[type="file"]').set_input_files(str(_FIXTURE_PDF))
    # Filing Type defaults to "10-K" (FILING_TYPES[0] in apps/web/lib/types.ts)
    # -- no need to touch that select for this upload.
    await page.locator("#period").fill("FY2023")
    await page.get_by_role("button", name="Upload", exact=True).click()

    row = page.locator("table tbody tr").filter(has_text=_FIXTURE_PDF.name)
    await row.get_by_text("Indexed", exact=True).wait_for(timeout=150_000)  # 2.5 min

    # Table columns: File Name, Type, Period, Status, Chunks, Quality, Ingested, Actions
    chunk_count_cell = row.locator("td").nth(4)
    chunk_count = await chunk_count_cell.inner_text()
    assert int(chunk_count) > 0
