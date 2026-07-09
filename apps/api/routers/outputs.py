from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/coverages", tags=["outputs"])

_501 = JSONResponse(
    status_code=501,
    content={
        "type": "https://stockanalyst.ai/errors/not-implemented",
        "title": "Not Implemented",
        "status": 501,
        "detail": "This endpoint is not yet implemented",
    },
)


@router.get("/{coverage_id}/outputs")
async def list_outputs(coverage_id: str):
    return _501


@router.get("/{coverage_id}/outputs/{output_id}")
async def get_output(coverage_id: str, output_id: str):
    return _501


@router.post("/{coverage_id}/outputs/{output_id}")
async def create_output(coverage_id: str, output_id: str):
    return _501
