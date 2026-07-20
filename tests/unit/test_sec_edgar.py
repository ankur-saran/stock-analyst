"""Unit tests for SECEdgarConnector — all HTTP calls mocked with httpx.MockTransport."""
from __future__ import annotations

import json
import time
from datetime import date
from unittest.mock import AsyncMock

import httpx
import pytest
from dateutil.relativedelta import relativedelta

from rag.connectors.sec_edgar import FilingMeta, SECEdgarConnector

AAPL_CIK = "0000320193"

COMPANY_TICKERS_PAYLOAD = {
    "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
    "1": {"cik_str": 789019, "ticker": "MSFT", "title": "Microsoft Corp"},
}


def _submissions_payload(form_type: str, count: int) -> dict:
    """Build a submissions JSON with one filing per year, most recent first."""
    forms, accessions, filed, reported = [], [], [], []
    today = date.today()
    for i in range(count):
        filed_date = today - relativedelta(years=i)
        forms.append(form_type)
        accessions.append(f"0000320193-{23 - i:02d}-{100000 + i:06d}")
        filed.append(filed_date.isoformat())
        reported.append(filed_date.isoformat())

    return {
        "filings": {
            "recent": {
                "form": forms,
                "accessionNumber": accessions,
                "filingDate": filed,
                "reportDate": reported,
                "primaryDocument": [f"doc{i}.htm" for i in range(count)],
            }
        }
    }


def _json_response(payload: dict) -> httpx.Response:
    return httpx.Response(200, content=json.dumps(payload).encode())


@pytest.fixture()
def mock_storage() -> AsyncMock:
    return AsyncMock()


# ── Test 1: get_cik ───────────────────────────────────────────────────────────


async def test_get_cik_returns_correct_cik(mock_storage: AsyncMock) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["user-agent"]
        return _json_response(COMPANY_TICKERS_PAYLOAD)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SECEdgarConnector(mock_storage, http_client=client)

    cik = await connector.get_cik("AAPL")

    assert cik == AAPL_CIK


# ── Test 2: list_filings ──────────────────────────────────────────────────────


async def test_list_filings_returns_filtered_and_sorted(mock_storage: AsyncMock) -> None:
    submissions = _submissions_payload("10-K", count=6)

    def handler(request: httpx.Request) -> httpx.Response:
        if "company_tickers" in str(request.url):
            return _json_response(COMPANY_TICKERS_PAYLOAD)
        return _json_response(submissions)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SECEdgarConnector(mock_storage, http_client=client)

    filings = await connector.list_filings("AAPL", "10-K", years=3)

    assert len(filings) == 3
    assert all(isinstance(f, FilingMeta) for f in filings)
    assert all(f.form_type == "10-K" for f in filings)
    assert all(f.cik == AAPL_CIK for f in filings)
    # sorted descending by filed_date
    assert filings == sorted(filings, key=lambda f: f.filed_date, reverse=True)


# ── Test 3: rate limiting ─────────────────────────────────────────────────────


async def test_rate_limiting_throttles_to_configured_rps(mock_storage: AsyncMock) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"ok")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SECEdgarConnector(mock_storage, rate_limit_rps=8.0, http_client=client)

    start = time.monotonic()
    for _ in range(15):
        await connector._fetch_with_rate_limit("https://data.sec.gov/dummy")
    elapsed = time.monotonic() - start

    assert elapsed >= 1.5


# ── Test 4: retries then fails on persistent 429 ─────────────────────────────


async def test_429_retried_three_times_then_filing_result_has_error(
    mock_storage: AsyncMock,
) -> None:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(429, content=b"rate limited")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    connector = SECEdgarConnector(
        mock_storage, http_client=client, retry_backoff_base=0.01
    )

    meta = FilingMeta(
        ticker="AAPL",
        cik=AAPL_CIK,
        form_type="10-K",
        accession_number="0000320193-23-000106",
        filed_date=date.today(),
        period_of_report="FY2023",
        primary_document_url="https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/aapl.htm",
        filing_index_url=(
            "https://www.sec.gov/Archives/edgar/data/320193/000032019323000106/"
            "0000320193-23-000106-index.json"
        ),
    )

    result = await connector.download_to_minio(meta, tenant_id="tenant-a", coverage_id="cov-1")

    assert result.download_success is False
    assert result.error is not None
    # one call for the filing-index lookup + one retry set (3 attempts) for the doc fetch,
    # so the doc-fetch path alone must have retried 3 times.
    assert call_count >= 3
    mock_storage.upload_file.assert_not_called()
