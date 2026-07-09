from fastapi import APIRouter
from fastapi.responses import JSONResponse

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


@router.post("")
async def create_coverage():
    return _501


@router.get("")
async def list_coverages():
    return _501


@router.get("/{coverage_id}")
async def get_coverage(coverage_id: str):
    return _501


@router.delete("/{coverage_id}")
async def delete_coverage(coverage_id: str):
    return _501
