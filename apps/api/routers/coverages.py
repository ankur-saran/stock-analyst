"""Coverage creation and listing.

Coverages are the tenant's per-ticker research workspace. ``industry_name``
is denormalized into responses via a join since the frontend renders it
directly on cards without a follow-up call — mirrors how documents.py
hand-rolls response dicts rather than returning ORM objects.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select

from shared.models import Coverage, CoverageStatusEnum, Industry

from apps.api.db import DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user

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
