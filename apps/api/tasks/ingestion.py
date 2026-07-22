"""Celery task: the full document ingestion pipeline.

Celery workers are sync, but almost every step here (Postgres, MinIO, Ollama,
Qdrant) is async in the underlying libraries. Rather than juggle sync and
async DB sessions side by side, the sync task hands the whole pipeline to a
single ``asyncio.run()`` call and does all I/O — including retry/failure
bookkeeping — inside that one event loop.

RLS on ``documents``/``coverages``/``task_queue`` means every session used
here must ``SET LOCAL app.current_tenant_id`` inside its transaction, exactly
like ``apps.api.db.get_db`` does for request-scoped sessions — otherwise the
policy hides the very rows this task needs to update.
"""
from __future__ import annotations

import asyncio
import hashlib
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from celery import Celery
from qdrant_client import QdrantClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rag.ingestion.chunkers.hierarchical import HierarchicalChunker
from rag.ingestion.parsers.pdf_parser import PDFParser
from rag.ingestion.parsers.table_extractor import TableExtractor
from rag.ingestion.pipeline import EmbeddingPipeline
from shared.config import Settings
from shared.models import (
    AgentAuditLog,
    Coverage,
    Document,
    IngestStatusEnum,
    TaskQueue,
    TaskStatusEnum,
)

from apps.api.services.storage import get_storage_service

logger = structlog.get_logger()

settings = Settings()

celery_app = Celery("stockanalyst", broker=settings.redis_url, backend=settings.redis_url)

_MIN_TEXT_COVERAGE = 0.5
_SEARCHABLE_CHUNK_TYPES = ("child", "table")

_engine = create_async_engine(settings.get_db_url(), pool_pre_ping=True, echo=False)
_AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)


class _DuplicateDocument(Exception):
    """Internal signal: hash matched an existing document in this coverage."""


class _LowTextCoverage(Exception):
    """Internal signal: parsed text coverage fell below the review threshold."""


# ── Celery entry point ──────────────────────────────────────────────────────


@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def ingest_document_task(self, document_id: str, coverage_id: str, tenant_id: str) -> None:
    asyncio.run(_execute(self, document_id, coverage_id, tenant_id))


async def _execute(task, document_id: str, coverage_id: str, tenant_id: str) -> None:
    await _set_task_status(task.request.id, tenant_id, TaskStatusEnum.running, started_at=True)
    try:
        await _run_ingestion(document_id, coverage_id, tenant_id)
    except (_DuplicateDocument, _LowTextCoverage):
        await _set_task_status(task.request.id, tenant_id, TaskStatusEnum.completed, completed_at=True)
        return
    except Exception as exc:  # noqa: BLE001 - retried below, marked failed once retries are exhausted
        logger.warning(
            "ingestion.attempt_failed",
            document_id=document_id,
            attempt=task.request.retries + 1,
            error=str(exc),
        )
        if task.request.retries < task.max_retries:
            task.retry(exc=exc, countdown=task.default_retry_delay)
        else:
            await _mark_document_failed(document_id, tenant_id, str(exc))
            await _set_task_status(
                task.request.id, tenant_id, TaskStatusEnum.failed, error=str(exc), completed_at=True
            )
            raise
    else:
        await _set_task_status(task.request.id, tenant_id, TaskStatusEnum.completed, completed_at=True)


# ── Pipeline ─────────────────────────────────────────────────────────────────


async def _run_ingestion(document_id: str, coverage_id: str, tenant_id: str) -> None:
    doc_uuid = uuid.UUID(document_id)
    coverage_uuid = uuid.UUID(coverage_id)

    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            document = await session.get(Document, doc_uuid)
            if document is None:
                raise ValueError(f"document {document_id} not found for tenant {tenant_id}")
            storage_path = document.storage_path
            file_name = document.file_name
            filing_type = document.filing_type
            period = document.period

    storage = get_storage_service()
    content = await storage.download_file(tenant_id, storage_path)
    file_hash = hashlib.sha256(content).hexdigest()

    duplicate_of = await _check_duplicate(doc_uuid, coverage_uuid, tenant_id, file_hash)
    if duplicate_of is not None:
        logger.info("ingestion.duplicate", document_id=document_id, duplicate_of=str(duplicate_of))
        raise _DuplicateDocument()

    tmp_path = _write_temp_file(content)
    try:
        parsed_doc = PDFParser().parse(tmp_path, document_id, file_name)
        tables = TableExtractor().extract_tables(tmp_path, parsed_doc, document_id, filing_type, period)

        if parsed_doc.overall_text_coverage < _MIN_TEXT_COVERAGE:
            await _set_document_status(doc_uuid, tenant_id, IngestStatusEnum.review_needed)
            raise _LowTextCoverage()

        chunks = HierarchicalChunker().chunk_document(
            parsed_doc,
            tables,
            tenant_id,
            coverage_id,
            filing_type=filing_type,
            period=period,
            document_name=file_name,
        )

        qdrant_client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
        pipeline = EmbeddingPipeline(ollama_url=settings.ollama_base_url, qdrant_client=qdrant_client)
        indexed_points = await pipeline.index_chunks(chunks, tenant_id)
        searchable_count = sum(1 for c in chunks if c.chunk_type in _SEARCHABLE_CHUNK_TYPES)

        await _finalize_success(
            doc_uuid=doc_uuid,
            coverage_uuid=coverage_uuid,
            tenant_id=tenant_id,
            file_hash=file_hash,
            chunk_count=searchable_count,
            indexed_points=indexed_points,
            quality_score=parsed_doc.overall_text_coverage,
            page_count=parsed_doc.total_pages,
        )
        logger.info("ingestion.complete", document_id=document_id, chunk_count=searchable_count)
    finally:
        tmp_path.unlink(missing_ok=True)


async def _check_duplicate(
    doc_uuid: uuid.UUID, coverage_uuid: uuid.UUID, tenant_id: str, file_hash: str
) -> uuid.UUID | None:
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            duplicate = (
                await session.execute(
                    select(Document).where(
                        Document.coverage_id == coverage_uuid,
                        Document.file_hash == file_hash,
                        Document.id != doc_uuid,
                    )
                )
            ).scalars().first()

            if duplicate is None:
                return None

            document = await session.get(Document, doc_uuid)
            document.file_hash = file_hash
            document.ingest_status = IngestStatusEnum.review_needed
            session.add(
                AgentAuditLog(
                    tenant_id=uuid.UUID(tenant_id),
                    coverage_id=coverage_uuid,
                    agent_name="DocumentIngestionAgent",
                    action="duplicate_detected",
                    input_hash=file_hash,
                    log_metadata={"duplicate_of": str(duplicate.id)},
                )
            )
            return duplicate.id


async def _finalize_success(
    *,
    doc_uuid: uuid.UUID,
    coverage_uuid: uuid.UUID,
    tenant_id: str,
    file_hash: str,
    chunk_count: int,
    indexed_points: int,
    quality_score: float,
    page_count: int,
) -> None:
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

            document = await session.get(Document, doc_uuid)
            document.chunk_count = chunk_count
            document.quality_score = quality_score
            document.ingest_status = IngestStatusEnum.indexed
            document.ingested_at = datetime.now(timezone.utc)
            document.page_count = page_count
            document.file_hash = file_hash

            coverage = await session.get(Coverage, coverage_uuid)
            coverage.document_count += 1
            coverage.last_updated = datetime.now(timezone.utc)

            session.add(
                AgentAuditLog(
                    tenant_id=uuid.UUID(tenant_id),
                    coverage_id=coverage_uuid,
                    agent_name="DocumentIngestionAgent",
                    action="ingest_complete",
                    input_hash=file_hash,
                    output_id=doc_uuid,
                    log_metadata={"chunk_count": chunk_count, "indexed_points": indexed_points},
                )
            )


async def _set_document_status(doc_uuid: uuid.UUID, tenant_id: str, status: IngestStatusEnum) -> None:
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            document = await session.get(Document, doc_uuid)
            if document is not None:
                document.ingest_status = status


async def _mark_document_failed(document_id: str, tenant_id: str, error: str) -> None:
    doc_uuid = uuid.UUID(document_id)
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            document = await session.get(Document, doc_uuid)
            if document is not None:
                document.ingest_status = IngestStatusEnum.failed
            session.add(
                AgentAuditLog(
                    tenant_id=uuid.UUID(tenant_id),
                    agent_name="DocumentIngestionAgent",
                    action="ingest_failed",
                    log_metadata={"error": error[:2000]},
                )
            )


async def _set_task_status(
    celery_task_id: str | None,
    tenant_id: str,
    status: TaskStatusEnum,
    *,
    started_at: bool = False,
    completed_at: bool = False,
    error: str | None = None,
) -> None:
    if not celery_task_id:
        return
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            task_row = (
                await session.execute(
                    select(TaskQueue).where(TaskQueue.celery_task_id == celery_task_id)
                )
            ).scalars().first()
            if task_row is None:
                return
            task_row.status = status
            if started_at:
                task_row.started_at = datetime.now(timezone.utc)
            if completed_at:
                task_row.completed_at = datetime.now(timezone.utc)
            if error is not None:
                task_row.error = error[:2000]


def _write_temp_file(content: bytes) -> Path:
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    try:
        tmp.write(content)
    finally:
        tmp.close()
    return Path(tmp.name)
