"""SEC EDGAR connector — fetches 10-K/10-Q/8-K filings and stores them in MinIO.

SEC EDGAR requires a descriptive User-Agent header (else requests get a 403) and
asks that callers stay under ~10 requests/second. Everything goes through
``_fetch_with_rate_limit`` so those two rules are enforced in one place.
"""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from apps.api.services.storage import StorageService

logger = structlog.get_logger()

DEFAULT_USER_AGENT = "StockAnalystAI contact@example.com"
COMPANY_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SUBMISSIONS_URL_TMPL = "https://data.sec.gov/submissions/CIK{cik}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

_QUARTER_MONTHS = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4}


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class FilingMeta:
    ticker: str
    cik: str
    form_type: str
    accession_number: str
    filed_date: date
    period_of_report: str
    primary_document_url: str
    filing_index_url: str


@dataclass
class FilingResult:
    meta: FilingMeta
    minio_path: str
    file_size_bytes: int
    download_success: bool
    error: str | None = None


class SECEdgarError(RuntimeError):
    """Raised when SEC EDGAR keeps rejecting a request after all retries."""


# ── Async-safe token bucket ──────────────────────────────────────────────────


class _TokenBucket:
    """Enforces a max requests/second rate without blocking the event loop.

    Capacity is fixed at 1 token (no burst) so throughput is a strict
    ``rate`` requests/second — a caller can never fire a batch faster than
    that just because tokens accumulated while idle.
    """

    def __init__(self, rate: float) -> None:
        self._rate = rate
        self._tokens = 1.0
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last
                self._last = now
                self._tokens = min(1.0, self._tokens + elapsed * self._rate)
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return
                wait = (1.0 - self._tokens) / self._rate
            await asyncio.sleep(wait)


# ── Connector ─────────────────────────────────────────────────────────────────


class SECEdgarConnector:
    def __init__(
        self,
        minio_storage: "StorageService",
        rate_limit_rps: float = 8.0,
        user_agent: str = DEFAULT_USER_AGENT,
        http_client: httpx.AsyncClient | None = None,
        retry_backoff_base: float = 0.5,
    ) -> None:
        self._storage = minio_storage
        self._bucket = _TokenBucket(rate_limit_rps)
        self._user_agent = user_agent
        self._client = http_client or httpx.AsyncClient(timeout=30.0)
        self._retry_backoff_base = retry_backoff_base
        self._cik_cache: dict[str, str] = {}

    # ── CIK lookup ────────────────────────────────────────────────────────────

    async def get_cik(self, ticker: str) -> str:
        """Return the 10-digit zero-padded CIK for ``ticker``, cached in memory."""
        ticker_upper = ticker.upper()
        if ticker_upper in self._cik_cache:
            return self._cik_cache[ticker_upper]

        raw = await self._fetch_with_rate_limit(COMPANY_TICKERS_URL)
        data: dict[str, dict[str, Any]] = json.loads(raw)

        for entry in data.values():
            entry_ticker = str(entry["ticker"]).upper()
            cik = str(entry["cik_str"]).zfill(10)
            self._cik_cache[entry_ticker] = cik

        if ticker_upper not in self._cik_cache:
            raise SECEdgarError(f"No CIK found for ticker '{ticker}'")
        return self._cik_cache[ticker_upper]

    # ── Filing listing ────────────────────────────────────────────────────────

    async def list_filings(
        self, ticker: str, form_type: str, years: int = 5
    ) -> list[FilingMeta]:
        cik = await self.get_cik(ticker)
        raw = await self._fetch_with_rate_limit(SUBMISSIONS_URL_TMPL.format(cik=cik))
        submissions = json.loads(raw)

        recent = submissions.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accession_numbers = recent.get("accessionNumber", [])
        filed_dates = recent.get("filingDate", [])
        report_dates = recent.get("reportDate", [])
        primary_documents = recent.get("primaryDocument", [])

        cutoff = date.today().replace(year=date.today().year - years)
        cik_unpadded = str(int(cik))

        filings: list[FilingMeta] = []
        for i, form in enumerate(forms):
            if form != form_type:
                continue

            filed_date = datetime.strptime(filed_dates[i], "%Y-%m-%d").date()
            if filed_date <= cutoff:
                continue

            report_date_raw = report_dates[i] if i < len(report_dates) else filed_dates[i]
            report_date = datetime.strptime(report_date_raw, "%Y-%m-%d").date()
            accession_number = accession_numbers[i]
            accession_no_dashes = accession_number.replace("-", "")
            primary_document = primary_documents[i] if i < len(primary_documents) else ""

            filings.append(
                FilingMeta(
                    ticker=ticker.upper(),
                    cik=cik,
                    form_type=form_type,
                    accession_number=accession_number,
                    filed_date=filed_date,
                    period_of_report=self._normalize_period(form_type, report_date),
                    primary_document_url=(
                        f"{ARCHIVES_BASE}/{cik_unpadded}/{accession_no_dashes}/{primary_document}"
                    ),
                    filing_index_url=(
                        f"{ARCHIVES_BASE}/{cik_unpadded}/{accession_no_dashes}/"
                        f"{accession_number}-index.json"
                    ),
                )
            )

        filings.sort(key=lambda f: f.filed_date, reverse=True)
        return filings

    def _normalize_period(self, form_type: str, report_date: date) -> str:
        if form_type == "10-Q":
            quarter = _QUARTER_MONTHS[report_date.month]
            return f"Q{quarter} {report_date.year}"
        return f"FY{report_date.year}"

    # ── Single filing fetch ───────────────────────────────────────────────────

    async def fetch_filing(
        self, ticker: str, form_type: str, year: int
    ) -> FilingResult | None:
        years_back = max(1, date.today().year - year + 1)
        filings = await self.list_filings(ticker, form_type, years=years_back)

        if form_type == "10-Q":
            match = next(
                (f for f in filings if f.period_of_report.endswith(f" {year}")), None
            )
        else:
            match = next((f for f in filings if f.period_of_report == f"FY{year}"), None)

        if match is None:
            return None

        return FilingResult(
            meta=match, minio_path="", file_size_bytes=0, download_success=False
        )

    # ── Download + store ──────────────────────────────────────────────────────

    async def download_to_minio(
        self, meta: FilingMeta, tenant_id: str, coverage_id: str
    ) -> FilingResult:
        try:
            document_url = await self._pick_document_url(meta)
            content = await self._fetch_with_rate_limit(document_url)
        except Exception as exc:  # noqa: BLE001 - surfaced via FilingResult.error
            logger.warning(
                "sec_edgar.download_failed",
                accession_number=meta.accession_number,
                error=str(exc),
            )
            return FilingResult(
                meta=meta, minio_path="", file_size_bytes=0, download_success=False,
                error=str(exc),
            )

        file_name = f"{meta.accession_number}.pdf"
        minio_path = await self._storage.upload_file(
            tenant_id, coverage_id, "raw", file_name, content
        )
        return FilingResult(
            meta=meta,
            minio_path=minio_path,
            file_size_bytes=len(content),
            download_success=True,
        )

    async def _pick_document_url(self, meta: FilingMeta) -> str:
        """Prefer a .pdf document in the filing index; fall back to the .htm primary doc."""
        try:
            raw_index = await self._fetch_with_rate_limit(meta.filing_index_url)
            index = json.loads(raw_index)
        except Exception:  # noqa: BLE001 - index lookup is best-effort
            return meta.primary_document_url

        items = index.get("directory", {}).get("item", [])
        pdf_item = next(
            (item for item in items if str(item.get("name", "")).lower().endswith(".pdf")),
            None,
        )
        if pdf_item is None:
            return meta.primary_document_url

        base = meta.filing_index_url.rsplit("/", 1)[0]
        return f"{base}/{pdf_item['name']}"

    # ── Rate-limited HTTP with retries ───────────────────────────────────────

    async def _fetch_with_rate_limit(self, url: str) -> bytes:
        headers = {"User-Agent": self._user_agent}
        last_error: Exception | None = None

        for attempt in range(3):
            await self._bucket.acquire()
            try:
                response = await self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_error = exc
            else:
                if response.status_code in (429, 503):
                    last_error = SECEdgarError(
                        f"SEC EDGAR returned {response.status_code} for {url}"
                    )
                else:
                    response.raise_for_status()
                    return response.content

            if attempt < 2:
                await asyncio.sleep(self._retry_backoff_base * (2**attempt))

        raise SECEdgarError(
            f"SEC EDGAR request failed after 3 attempts: {url}"
        ) from last_error
