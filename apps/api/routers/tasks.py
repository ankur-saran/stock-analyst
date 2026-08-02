import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import select, text

from shared.config import Settings
from shared.models import Coverage, Industry, TaskQueue
from shared.streaming import StreamingService

from agents.orchestrator.tools import dispatch_task

from apps.api.db import AsyncSessionLocal, DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user, get_current_user_ws, role_required

settings = Settings()

router = APIRouter(prefix="/tasks", tags=["tasks"])

# Separate router (same "/coverages" prefix other coverage-nested routers use,
# e.g. documents.py/outputs.py) since task dispatch is nested under a
# coverage even though the industry primer itself is stored tenant-lessly.
coverage_tasks_router = APIRouter(prefix="/coverages", tags=["tasks"])

# No prefix -- the WS path is "/ws/tasks/{task_id}" at the app root, not
# nested under "/tasks" like `router` above.
ws_router = APIRouter(tags=["tasks"])

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
        # The raw serialized AgentOutput (agents.orchestrator.tasks._run_agent
        # always writes this) -- the only way to read a rejected or
        # prerequisite-missing output's content, since those never become a
        # research_outputs row.
        "result": task.result,
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
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
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


# Agents dispatched generically by name — industry_analyst is deliberately
# absent (it has its own endpoint above with an industry_name-shaped body);
# orchestrator/document_ingestion are never dispatched as a standalone task.
_DISPATCHABLE_AGENTS = {"lynch_pitch", "munger_invert", "earnings_monitor", "kpi_tracker"}


class AgentTaskRequest(BaseModel):
    skill: str = "default"
    payload: dict[str, Any] = {}


@coverage_tasks_router.post("/{coverage_id}/tasks/{agent_name}", status_code=202)
async def run_agent_task_endpoint(
    coverage_id: str,
    agent_name: str,
    body: AgentTaskRequest,
    current_user: CurrentUser = Depends(role_required("analyst")),
) -> dict[str, Any]:
    if agent_name not in _DISPATCHABLE_AGENTS:
        raise _not_found()
    try:
        coverage_uuid = uuid.UUID(coverage_id)
    except ValueError:
        raise _not_found()

    # Bare session, same reasoning as run_industry_analysis above:
    # dispatch_task commits mid-flight and a still-open session.begin() block
    # can't tolerate that.
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(current_user.tenant_id)},
            )
            coverage = await session.get(Coverage, coverage_uuid)
            if coverage is None or coverage.tenant_id != current_user.tenant_id:
                raise _not_found()

        task_id = await dispatch_task(
            agent=agent_name,
            skill=body.skill,
            payload=body.payload,
            coverage_id=str(coverage.id),
            tenant_id=str(current_user.tenant_id),
            db=session,
        )

    return {"task_id": task_id, "status": "queued"}


@ws_router.websocket("/ws/tasks/{task_id}")
async def task_websocket(
    websocket: WebSocket,
    task_id: str,
    current_user: CurrentUser = Depends(get_current_user_ws),
) -> None:
    await websocket.accept()

    try:
        task_uuid = uuid.UUID(task_id)
    except ValueError:
        await websocket.close(code=1008, reason="Invalid task_id")
        return

    # Bare session, not `DbSession`: `TenantMiddleware` is `BaseHTTPMiddleware`
    # and never runs for the "websocket" ASGI scope, so `request.state.tenant_id`
    # (what `DbSession`/`get_db` relies on) was never set. Same
    # bare-session-plus-`SET LOCAL` pattern `orchestrator/tasks.py` uses.
    async with AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"),
                {"tid": str(current_user.tenant_id)},
            )
            task = await session.get(TaskQueue, task_uuid)

        if task is None or task.tenant_id != current_user.tenant_id:
            await websocket.close(code=1008, reason="Task not found")
            return

        if task.status.value == "completed":
            # Reconnected after the task already finished -- Redis pub/sub has
            # no replay, so send the final state directly instead of waiting
            # on a channel nothing will ever publish to again.
            output_id = (task.result or {}).get("message_id")
            await websocket.send_json({"type": "already_complete", "output_id": output_id})
            await websocket.close()
            return

        if task.status.value == "failed":
            await websocket.send_json(
                {
                    "type": "error",
                    "code": "TASK_FAILED",
                    "retry_count": 0,
                    "detail": task.error or "",
                }
            )
            await websocket.close()
            return

    streaming_svc = StreamingService(settings.redis_url)
    try:
        async for event in streaming_svc.subscribe_events(task_id):
            await websocket.send_json(event)
            if event.get("type") in ("complete", "error", "partial"):
                break
    except WebSocketDisconnect:
        pass  # client disconnected — no cleanup needed beyond subscribe_events' own finally
