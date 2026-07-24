"""Coverage creation and listing.

Coverages are the tenant's per-ticker research workspace. ``industry_name``
is denormalized into responses via a join since the frontend renders it
directly on cards without a follow-up call — mirrors how documents.py
hand-rolls response dicts rather than returning ORM objects.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select, text

from shared.models import Coverage, CoverageStatusEnum, Industry, KpiTimeseries

from agents.orchestrator.agent import OrchestratorAgent
from agents.shared.message import AgentMessage, AgentType

from apps.api.db import AsyncSessionLocal, DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user, role_required

router = APIRouter(prefix="/coverages", tags=["coverages"])

_501 = JSONResponse(
    status_code=501,
    content={
        "type": "https://stockanalyst.ai/errors/not-implemented",
        "title": "Not Implemented",
        "status": 501,
        "detail": "This endpoint is not yet implemented",
    },
)

_EXCHANGES = {"NYSE", "NASDAQ", "LSE", "TSX", "ASX", "Other"}


def _problem(status: int, title: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={
            "type": f"https://stockanalyst.ai/errors/{title.lower().replace(' ', '-')}",
            "title": title,
            "status": status,
            "detail": detail,
        },
    )


class CoverageCreateRequest(BaseModel):
    ticker: str
    company_name: str
    exchange: str
    industry_id: Optional[uuid.UUID] = None

    @field_validator("ticker")
    @classmethod
    def _uppercase_ticker(cls, v: str) -> str:
        v = v.strip().upper()
        if not v:
            raise ValueError("ticker must not be empty")
        return v

    @field_validator("company_name")
    @classmethod
    def _strip_company_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("company_name must not be empty")
        return v

    @field_validator("exchange")
    @classmethod
    def _validate_exchange(cls, v: str) -> str:
        if v not in _EXCHANGES:
            raise ValueError(f"exchange must be one of {sorted(_EXCHANGES)}")
        return v


def _coverage_dict(c: Coverage, industry_name: Optional[str]) -> dict[str, Any]:
    return {
        "id": str(c.id),
        "ticker": c.ticker,
        "company_name": c.company_name,
        "exchange": c.exchange,
        "industry_id": str(c.industry_id) if c.industry_id else None,
        "industry_name": industry_name,
        "status": c.status.value,
        "document_count": c.document_count,
        "last_updated": c.last_updated.isoformat() if c.last_updated else None,
        "created_at": c.created_at.isoformat(),
    }


@router.post("", status_code=201)
async def create_coverage(
    body: CoverageCreateRequest,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    industry: Industry | None = None
    if body.industry_id is not None:
        industry = await db.get(Industry, body.industry_id)
        if industry is None:
            raise _problem(422, "Unprocessable Entity", "industry_id does not reference a known industry")

    existing = await db.execute(
        select(Coverage.id).where(
            Coverage.tenant_id == current_user.tenant_id,
            Coverage.ticker == body.ticker,
            Coverage.exchange == body.exchange,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise _problem(409, "Conflict", f"Coverage for {body.ticker} on {body.exchange} already exists")

    coverage = Coverage(
        id=uuid.uuid4(),
        tenant_id=current_user.tenant_id,
        ticker=body.ticker,
        company_name=body.company_name,
        exchange=body.exchange,
        industry_id=body.industry_id,
        created_by=current_user.user_id,
        status=CoverageStatusEnum.setup,
        document_count=0,
        last_updated=None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(coverage)
    await db.flush()

    return _coverage_dict(coverage, industry.name if industry is not None else None)


@router.get("")
async def list_coverages(
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    stmt = (
        select(Coverage, Industry.name)
        .outerjoin(Industry, Coverage.industry_id == Industry.id)
        .where(Coverage.tenant_id == current_user.tenant_id)
        .order_by(Coverage.created_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    return [_coverage_dict(c, industry_name) for c, industry_name in rows]


@router.get("/{coverage_id}")
async def get_coverage(
    coverage_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        coverage_uuid = uuid.UUID(coverage_id)
    except ValueError:
        raise _problem(404, "Not Found", "Coverage not found")

    stmt = (
        select(Coverage, Industry.name)
        .outerjoin(Industry, Coverage.industry_id == Industry.id)
        .where(Coverage.id == coverage_uuid, Coverage.tenant_id == current_user.tenant_id)
    )
    row = (await db.execute(stmt)).first()
    if row is None:
        raise _problem(404, "Not Found", "Coverage not found")

    coverage, industry_name = row
    return _coverage_dict(coverage, industry_name)


@router.delete("/{coverage_id}")
async def delete_coverage(coverage_id: str):
    return _501


class OrchestrateRequest(BaseModel):
    user_request: str

    @field_validator("user_request")
    @classmethod
    def _strip_user_request(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_request must not be empty")
        return v


@router.post("/{coverage_id}/orchestrate")
async def orchestrate(
    coverage_id: str,
    body: OrchestrateRequest,
    current_user: CurrentUser = Depends(role_required("analyst")),
) -> dict[str, Any]:
    try:
        coverage_uuid = uuid.UUID(coverage_id)
    except ValueError:
        raise _problem(404, "Not Found", "Coverage not found")

    message = AgentMessage(
        sender=AgentType.ORCHESTRATOR,
        recipient=AgentType.ORCHESTRATOR,
        task_id=str(uuid.uuid4()),
        coverage_id=str(coverage_uuid),
        tenant_id=str(current_user.tenant_id),
        payload={"user_request": body.user_request},
    )

    # Deliberately not `db: DbSession` (the get_db dependency): that helper
    # wraps the *whole request* in one `session.begin()` block, but dispatching
    # a plan runs dispatch_task's add/commit/refresh/commit followed by
    # BaseAgent's own audit-log commit — multiple mid-flight commits that a
    # still-open `session.begin()` context manager around them raises
    # InvalidRequestError over. A bare session left to autobegin its own
    # transactions tolerates that same sequence fine.
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SET LOCAL app.current_tenant_id = :tid"),
            {"tid": str(current_user.tenant_id)},
        )
        orchestrator = OrchestratorAgent(db_session=session)
        try:
            output = await orchestrator.run(message)
        except ValueError as exc:
            raise _problem(502, "Bad Gateway", f"Orchestrator failed to produce a valid plan: {exc}")

    return json.loads(output.content)


# --- KPI dashboard ------------------------------------------------------------

# KPIs that are standard financial-statement figures (roughly the `default`
# bucket in infra/kpi_definitions.yaml, plus a few sector variants) -- every
# other KPI name is treated as an operational/sector-specific metric. Purely
# a display grouping for the dashboard tabs; extraction itself doesn't care.
_FINANCIAL_KPI_NAMES = {
    "revenue", "gross_profit", "gross_margin", "gross_margin_pct", "ebitda",
    "net_income", "eps_diluted", "fcf", "capex", "net_debt", "cash_equivalents",
    "cash_and_equivalents", "shares_outstanding", "operating_margin", "total_debt",
}

_PERIOD_YEAR_RE = re.compile(r"\d{4}")
_PERIOD_QUARTER_RE = re.compile(r"Q(\d)", re.IGNORECASE)


def _kpi_category(kpi_name: str) -> str:
    return "financial" if kpi_name in _FINANCIAL_KPI_NAMES else "operational"


def _period_sort_key(period: str) -> tuple[int, int]:
    year_match = _PERIOD_YEAR_RE.search(period)
    quarter_match = _PERIOD_QUARTER_RE.search(period)
    year = int(year_match.group()) if year_match else 0
    quarter = int(quarter_match.group(1)) if quarter_match else 0
    return (year, quarter)


def _data_points_with_yoy(rows: list[KpiTimeseries]) -> list[dict[str, Any]]:
    """Sort a single KPI's rows chronologically and attach YoY change per period_type."""
    ordered = sorted(rows, key=lambda r: _period_sort_key(r.period))

    points: list[dict[str, Any]] = []
    last_value_by_period_type: dict[str, float] = {}
    for row in ordered:
        period_type = row.period_type.value
        prior_value = last_value_by_period_type.get(period_type)
        yoy_change_pct = (
            (row.value - prior_value) / abs(prior_value) * 100
            if prior_value is not None and prior_value != 0
            else None
        )
        last_value_by_period_type[period_type] = row.value

        points.append(
            {
                "period": row.period,
                "period_type": period_type,
                "value": row.value,
                "unit": row.unit,
                "is_restated": row.is_restated,
                "restatement_note": row.restatement_note,
                "citation": row.citation,
                "yoy_change_pct": yoy_change_pct,
                "extracted_at": row.extracted_at.isoformat(),
            }
        )
    return points


async def _require_coverage(coverage_id: str, db: DbSession, current_user: CurrentUser) -> uuid.UUID:
    try:
        coverage_uuid = uuid.UUID(coverage_id)
    except ValueError:
        raise _problem(404, "Not Found", "Coverage not found")

    exists = await db.execute(
        select(Coverage.id).where(
            Coverage.id == coverage_uuid, Coverage.tenant_id == current_user.tenant_id
        )
    )
    if exists.scalar_one_or_none() is None:
        raise _problem(404, "Not Found", "Coverage not found")
    return coverage_uuid


@router.get("/{coverage_id}/kpis")
async def list_kpis(
    coverage_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    coverage_uuid = await _require_coverage(coverage_id, db, current_user)

    rows = (
        await db.execute(
            select(KpiTimeseries).where(KpiTimeseries.coverage_id == coverage_uuid)
        )
    ).scalars().all()

    by_kpi: dict[str, list[KpiTimeseries]] = {}
    for row in rows:
        by_kpi.setdefault(row.kpi_name, []).append(row)

    kpis = [
        {
            "kpi_name": kpi_name,
            "category": _kpi_category(kpi_name),
            "unit": kpi_rows[0].unit,
            "data_points": _data_points_with_yoy(kpi_rows),
        }
        for kpi_name, kpi_rows in sorted(by_kpi.items())
    ]
    return {"coverage_id": coverage_id, "kpis": kpis}


@router.get("/{coverage_id}/kpis/{kpi_name}")
async def get_kpi(
    coverage_id: str,
    kpi_name: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    coverage_uuid = await _require_coverage(coverage_id, db, current_user)

    rows = (
        await db.execute(
            select(KpiTimeseries).where(
                KpiTimeseries.coverage_id == coverage_uuid,
                KpiTimeseries.kpi_name == kpi_name,
            )
        )
    ).scalars().all()
    if not rows:
        raise _problem(404, "Not Found", f"No KPI data found for '{kpi_name}' on this coverage")

    return {
        "coverage_id": coverage_id,
        "kpi_name": kpi_name,
        "category": _kpi_category(kpi_name),
        "unit": rows[0].unit,
        "data_points": _data_points_with_yoy(list(rows)),
    }
