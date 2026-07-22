import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from apps.api.db import DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user
from shared.models import TaskQueue

router = APIRouter(prefix="/tasks", tags=["tasks"])

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
