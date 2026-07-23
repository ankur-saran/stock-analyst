import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select, text

from shared.models import Coverage, Industry, TaskQueue

from agents.orchestrator.tools import dispatch_task

from apps.api.db import AsyncSessionLocal, DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user, role_required

router = APIRouter(prefix="/tasks", tags=["tasks"])

# Separate router (same "/coverages" prefix other coverage-nested routers use,
# e.g. documents.py/outputs.py) since task dispatch is nested under a
# coverage even though the industry primer itself is stored tenant-lessly.
coverage_tasks_router = APIRouter(prefix="/coverages", tags=["tasks"])

_501 = JSONResponse(
    status_code=501,
    content={
        "type": "https://stockanalyst.ai/errors/not-implemented",
        "title": "Not Implemented",
        "status": 501,
        "detail": "This endpoint is not yet implemented",
    },
)


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "type": "https://stockanalyst.ai/errors/not-found",
            "title": "Not Found",
            "status": 404,
            "detail": "Task not found",
        },
    )


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        raise _not_found()

    task = await db.get(TaskQueue, task_uuid)
    if task is None:
        raise _not_found()

    return {
        "task_id": str(task.id),
        "status": task.status.value,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "completed_at": task.completed_at.isoformat() if task.completed_at else None,
        "error": task.error,
    }


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    return _501


class IndustryAnalysisRequest(BaseModel):
    industry_name: str

    @field_validator("industry_name")
    @classmethod
    def _strip_industry_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("industry_name must not be empty")
        return v


@coverage_tasks_router.post("/{coverage_id}/tasks/industry-analysis", status_code=202)
async def run_industry_analysis(
    coverage_id: str,
    body: IndustryAnalysisRequest,
    current_user: CurrentUser = Depends(role_required("analyst")),
) -> dict[str, Any]:
    try:
        coverage_uuid = uuid.UUID(coverage_id)
    except ValueError:
        raise _not_found()

    # Bare session (not `db: DbSession`) because `dispatch_task` commits
    # mid-flight (INSERT task_queue row, then update it with the celery task
    # id) — a still-open `session.begin()` block like `get_db` opens can't
    # tolerate that, same reasoning as `coverages.orchestrate`.
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SET LOCAL app.current_tenant_id = :tid"),
                {"tid": str(current_user.tenant_id)},
            )
            coverage = await session.get(Coverage, coverage_uuid)
            if coverage is None or coverage.tenant_id != current_user.tenant_id:
                raise _not_found()

            industry = (
                await session.execute(select(Industry).where(Industry.name == body.industry_name))
            ).scalar_one_or_none()
            if industry is None:
                industry = Industry(id=uuid.uuid4(), name=body.industry_name)
                session.add(industry)
                await session.flush()

            if coverage.industry_id is None:
                coverage.industry_id = industry.id

        task_id = await dispatch_task(
            agent="industry_analyst",
            skill="generate_primer",
            payload={"industry_name": industry.name, "industry_id": str(industry.id)},
            coverage_id=str(coverage.id),
            tenant_id=str(current_user.tenant_id),
            db=session,
        )

    return {"industry_id": str(industry.id), "task_id": task_id, "status": "queued"}
