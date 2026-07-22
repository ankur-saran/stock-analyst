"""Document upload, listing, and deletion.

POST accepts either a multipart file upload or a JSON body naming a filing to
pull from SEC EDGAR; both paths create a ``documents`` row and enqueue
:func:`apps.api.tasks.ingestion.ingest_document_task`. Every handler resolves
the coverage first and checks it belongs to the caller's tenant — Postgres
RLS (via ``apps.api.db.get_db``'s ``SET LOCAL app.current_tenant_id``)
already hides cross-tenant rows, but a 404 raised here doesn't depend on that
being wired correctly.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from rag.connectors.qdrant_client import QdrantConnector
from rag.connectors.sec_edgar import SECEdgarConnector
from shared.config import Settings
from shared.models import Coverage, Document, IngestStatusEnum, TaskQueue

from apps.api.db import DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user
from apps.api.services.storage import StorageService, get_storage_service
from apps.api.tasks.ingestion import ingest_document_task

router = APIRouter(prefix="/coverages", tags=["documents"])

settings = Settings()

_MAX_UPLOAD_BYTES = 100 * 1024 * 1024  # 100MB
_QDRANT_COLLECTION_PREFIX = "tenant"  # must match EmbeddingPipeline.collection_prefix


def _problem(status: int, title: str, detail: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={
            "type": f"https://stockanalyst.ai/errors/{title.lower().replace(' ', '-')}",
            "title": title,
            "status": status,
            "detail": detail,
        },
    )


async def _get_owned_coverage(db: AsyncSession, coverage_id: str, tenant_id: uuid.UUID) -> Coverage:
    try:
        coverage_uuid = uuid.UUID(coverage_id)
    except ValueError:
        raise _problem(404, "Not Found", "Coverage not found")

    coverage = await db.get(Coverage, coverage_uuid)
    if coverage is None or coverage.tenant_id != tenant_id:
        raise _problem(404, "Not Found", "Coverage not found")
    return coverage


# ── POST /{coverage_id}/documents ───────────────────────────────────────────


@router.post("/{coverage_id}/documents", status_code=202)
async def upload_document(
    coverage_id: str,
    request: Request,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
) -> dict[str, Any]:
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)

    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > _MAX_UPLOAD_BYTES:
        raise _problem(413, "Payload Too Large", "File exceeds the 100MB upload limit")

    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        document = await _create_document_from_upload(request, coverage, current_user, storage, db)
    elif content_type.startswith("application/json"):
        document = await _create_document_from_sec_fetch(request, coverage, current_user, storage, db)
    else:
        raise _problem(
            415,
            "Unsupported Media Type",
            "Content-Type must be multipart/form-data (file upload) or application/json (SEC fetch)",
        )

    task = ingest_document_task.delay(str(document.id), str(coverage.id), str(current_user.tenant_id))
    db.add(
        TaskQueue(
            tenant_id=current_user.tenant_id,
            coverage_id=coverage.id,
            task_type="document_ingestion",
            celery_task_id=task.id,
        )
    )

    return {"document_id": str(document.id), "task_id": task.id, "status": "queued"}


async def _create_document_from_upload(
    request: Request,
    coverage: Coverage,
    current_user: CurrentUser,
    storage: StorageService,
    db: AsyncSession,
) -> Document:
    form = await request.form()
    upload = form.get("file")
    if upload is None or not hasattr(upload, "read"):
        raise _problem(422, "Unprocessable Entity", "file field is required")

    filing_type = form.get("filing_type")
    period = form.get("period")
    source = form.get("source") or "upload"
    if not filing_type or not period:
        raise _problem(422, "Unprocessable Entity", "filing_type and period are required")

    content = await upload.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise _problem(413, "Payload Too Large", "File exceeds the 100MB upload limit")

    storage_path = await storage.upload_file(
        str(current_user.tenant_id), str(coverage.id), "raw", upload.filename, content
    )

    document = Document(
        id=uuid.uuid4(),
        coverage_id=coverage.id,
        tenant_id=current_user.tenant_id,
        file_name=upload.filename,
        filing_type=str(filing_type),
        period=str(period),
        source=str(source),
        storage_path=storage_path,
        ingest_status=IngestStatusEnum.pending,
    )
    db.add(document)
    return document


async def _create_document_from_sec_fetch(
    request: Request,
    coverage: Coverage,
    current_user: CurrentUser,
    storage: StorageService,
    db: AsyncSession,
) -> Document:
    body = await request.json()
    ticker = body.get("ticker")
    form_type = body.get("form_type")
    year = body.get("year")
    if not ticker or not form_type or not year:
        raise _problem(422, "Unprocessable Entity", "ticker, form_type, and year are required")

    sec = SECEdgarConnector(minio_storage=storage)
    filing = await sec.fetch_filing(str(ticker), str(form_type), int(year))
    if filing is None:
        raise _problem(404, "Not Found", f"No {form_type} filing found for {ticker} {year}")

    result = await sec.download_to_minio(filing.meta, str(current_user.tenant_id), str(coverage.id))
    if not result.download_success:
        raise _problem(502, "Bad Gateway", f"Failed to download filing from SEC EDGAR: {result.error}")

    document = Document(
        id=uuid.uuid4(),
        coverage_id=coverage.id,
        tenant_id=current_user.tenant_id,
        file_name=result.minio_path.rsplit("/", 1)[-1],
        filing_type=str(form_type),
        period=filing.meta.period_of_report,
        source="sec_edgar",
        source_url=filing.meta.primary_document_url,
        storage_path=result.minio_path,
        ingest_status=IngestStatusEnum.pending,
    )
    db.add(document)
    return document


# ── GET /{coverage_id}/documents ────────────────────────────────────────────


@router.get("/{coverage_id}/documents")
async def list_documents(
    coverage_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
    ingest_status: IngestStatusEnum | None = None,
) -> list[dict[str, Any]]:
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)

    stmt = select(Document).where(Document.coverage_id == coverage.id)
    if ingest_status is not None:
        stmt = stmt.where(Document.ingest_status == ingest_status)

    rows = (await db.execute(stmt)).scalars().all()
    return [
        {
            "id": str(d.id),
            "file_name": d.file_name,
            "filing_type": d.filing_type,
            "period": d.period,
            "ingest_status": d.ingest_status.value,
            "chunk_count": d.chunk_count,
            "quality_score": d.quality_score,
            "ingested_at": d.ingested_at.isoformat() if d.ingested_at else None,
        }
        for d in rows
    ]


# ── DELETE /{coverage_id}/documents/{document_id} ───────────────────────────


@router.delete("/{coverage_id}/documents/{document_id}", status_code=204)
async def delete_document(
    coverage_id: str,
    document_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
    storage: StorageService = Depends(get_storage_service),
) -> None:
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)

    try:
        doc_uuid = uuid.UUID(document_id)
    except ValueError:
        raise _problem(404, "Not Found", "Document not found")

    document = await db.get(Document, doc_uuid)
    if document is None or document.coverage_id != coverage.id:
        raise _problem(404, "Not Found", "Document not found")

    qdrant = QdrantConnector(host=settings.qdrant_host, port=settings.qdrant_port)
    collection = f"{_QDRANT_COLLECTION_PREFIX}_{current_user.tenant_id}"
    await qdrant.delete_by_filter(
        collection=collection,
        filter_={
            "must": [
                {"key": "document_id", "match": {"value": str(document.id)}},
                {"key": "tenant_id", "match": {"value": str(current_user.tenant_id)}},
            ]
        },
    )

    await storage.delete_file(str(current_user.tenant_id), document.storage_path)

    coverage.document_count = max(0, coverage.document_count - 1)
    await db.delete(document)
