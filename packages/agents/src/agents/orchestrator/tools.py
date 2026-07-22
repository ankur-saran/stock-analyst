"""Tool functions callable by the Orchestrator agent.

Every query relies on the caller having already ``SET LOCAL
app.current_tenant_id`` on ``db`` (see ``apps.api.db.get_db``) so RLS scopes
results to the right tenant — these functions add explicit ``tenant_id``
filters only where the spec calls for it (``check_coverage_exists``), not as
a substitute for RLS.
"""
from __future__ import annotations

import uuid
from typing import Any

from shared.models import Coverage, Document, Industry, TaskQueue, TaskStatusEnum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shared.message import AgentType
from agents.orchestrator.tasks import run_agent_task


async def check_coverage_exists(coverage_id: str, tenant_id: str, db: AsyncSession) -> bool:
    """Query coverages table with both IDs (RLS enforces tenant isolation)."""
    result = await db.execute(
        select(Coverage.id).where(
            Coverage.id == uuid.UUID(coverage_id),
            Coverage.tenant_id == uuid.UUID(tenant_id),
        )
    )
    return result.scalar_one_or_none() is not None


async def check_industry_loaded(coverage_id: str, db: AsyncSession) -> bool:
    """Join coverages -> industries; check industries.primer_content IS NOT NULL."""
    result = await db.execute(
        select(Industry.id)
        .join(Coverage, Coverage.industry_id == Industry.id)
        .where(
            Coverage.id == uuid.UUID(coverage_id),
            Industry.primer_content.is_not(None),
        )
    )
    return result.scalar_one_or_none() is not None


async def check_filing_count(
    coverage_id: str, form_type: str, min_years: int, db: AsyncSession
) -> dict[str, Any]:
    """Count documents of the given filing type for a coverage.

    Returns ``{"count": int, "years_covered": list[str], "meets_minimum": bool}``
    — ``count`` is total matching documents, ``years_covered`` the distinct
    filing periods, and ``meets_minimum`` compares distinct years to
    ``min_years`` (a coverage with 5 duplicate filings for one year still
    doesn't meet a 3-year minimum).
    """
    result = await db.execute(
        select(Document.period).where(
            Document.coverage_id == uuid.UUID(coverage_id),
            Document.filing_type == form_type,
        )
    )
    periods = [row[0] for row in result.all()]
    years_covered = sorted(set(periods))
    return {
        "count": len(periods),
        "years_covered": years_covered,
        "meets_minimum": len(years_covered) >= min_years,
    }


async def list_available_agents() -> list[str]:
    return [t.value for t in AgentType if t != AgentType.ORCHESTRATOR]


async def dispatch_task(
    agent: str,
    skill: str,
    payload: dict[str, Any],
    coverage_id: str,
    tenant_id: str,
    db: AsyncSession,
) -> str:
    """INSERT into task_queue with status="queued" and enqueue the Celery task."""
    task = TaskQueue(
        tenant_id=uuid.UUID(tenant_id),
        coverage_id=uuid.UUID(coverage_id),
        task_type=f"{agent}.{skill}",
        status=TaskStatusEnum.queued,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    async_result = run_agent_task.delay(str(task.id), agent, skill, payload)
    task.celery_task_id = async_result.id
    await db.commit()

    return str(task.id)


async def get_task_status(task_id: str, db: AsyncSession) -> dict[str, Any]:
    """Query task_queue by task_id; return status, started_at, completed_at, error."""
    task = await db.get(TaskQueue, uuid.UUID(task_id))
    if task is None:
        return {"status": "not_found"}
    return {
        "status": task.status.value,
        "started_at": task.started_at,
        "completed_at": task.completed_at,
        "error": task.error,
    }
