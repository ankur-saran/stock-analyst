from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/coverages", tags=["documents"])

_501 = JSONResponse(
    status_code=501,
    content={
        "type": "https://stockanalyst.ai/errors/not-implemented",
        "title": "Not Implemented",
        "status": 501,
        "detail": "This endpoint is not yet implemented",
    },
)


@router.post("/{coverage_id}/documents")
async def upload_document(coverage_id: str):
    return _501


@router.get("/{coverage_id}/documents")
async def list_documents(coverage_id: str):
    return _501


@router.delete("/{coverage_id}/documents/{doc_id}")
async def delete_document(coverage_id: str, doc_id: str):
    return _501
