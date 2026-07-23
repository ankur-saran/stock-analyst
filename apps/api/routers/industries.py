"""Industry lookup.

Read-only reference data used to populate the New Coverage form's industry
select; industries are shared across tenants (no tenant_id column) and
managed out-of-band (e.g. by the industry primer generation pipeline).
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from shared.models import Industry

from apps.api.db import DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/industries", tags=["industries"])


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "type": "https://stockanalyst.ai/errors/not-found",
            "title": "Not Found",
            "status": 404,
            "detail": "Industry not found",
        },
    )


@router.get("")
async def list_industries(
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    stmt = select(Industry).order_by(Industry.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": str(i.id), "name": i.name} for i in rows]


@router.get("/{industry_id}")
async def get_industry(
    industry_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        industry_uuid = uuid.UUID(industry_id)
    except ValueError:
        raise _not_found()

    industry = await db.get(Industry, industry_uuid)
    if industry is None:
        raise _not_found()

    return {
        "id": str(industry.id),
        "name": industry.name,
        "primer_content": industry.primer_content,
        "primer_citations": industry.primer_citations,
        "word_count": industry.word_count,
        "llm_used": industry.llm_used,
        "updated_at": industry.updated_at.isoformat() if industry.updated_at else None,
    }
