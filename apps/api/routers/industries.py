"""Industry lookup.

Read-only reference data used to populate the New Coverage form's industry
select; industries are shared across tenants (no tenant_id column) and
managed out-of-band (e.g. by the industry primer generation pipeline).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import select

from shared.models import Industry

from apps.api.db import DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/industries", tags=["industries"])


@router.get("")
async def list_industries(
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> list[dict[str, Any]]:
    stmt = select(Industry).order_by(Industry.name)
    rows = (await db.execute(stmt)).scalars().all()
    return [{"id": str(i.id), "name": i.name} for i in rows]
