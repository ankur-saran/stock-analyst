from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/admin", tags=["admin"])

_501 = JSONResponse(
    status_code=501,
    content={
        "type": "https://stockanalyst.ai/errors/not-implemented",
        "title": "Not Implemented",
        "status": 501,
        "detail": "This endpoint is not yet implemented",
    },
)


@router.get("/tenants")
async def list_tenants():
    return _501


@router.get("/usage")
async def get_usage():
    return _501


@router.get("/agents/health")
async def agents_health():
    return _501
