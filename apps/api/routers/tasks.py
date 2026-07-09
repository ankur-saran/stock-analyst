from fastapi import APIRouter
from fastapi.responses import JSONResponse

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


@router.get("/{task_id}")
async def get_task(task_id: str):
    return _501


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    return _501
