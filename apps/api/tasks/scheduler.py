"""Celery Beat task: daily sweep for new SEC filings on every active coverage.

Runs once a day (see ``apps/api/celery_config.py``'s ``beat_schedule`` —
``EARNINGS_MONITOR_SCHEDULE`` documents the crontab this task is meant to
run under). For each ``active`` coverage: list the latest 10-Q/10-K filings
from SEC EDGAR, and for the newest one that is both newer than
``coverage.last_updated`` and not already a ``documents`` row (matched by
``source_url``) — ingest it, then dispatch ``EarningsMonitorAgent``, then
notify analyst/senior_analyst users once that agent run actually completes
and its output is enforcer-approved.

Ingestion and the Celery worker's own agent-dispatch pipeline are reused
directly (``ingest_document_task``, ``run_agent_task``) rather than
duplicated here. The "notify after the agent finishes" step can't be a
plain sequential call, though — ``run_agent_task`` runs asynchronously in a
worker process and this task doesn't block on its result — so it's wired up
as a Celery ``link`` callback (``notify_earnings_complete_task``), which
Celery invokes automatically once ``run_agent_task`` succeeds.

Celery Beat is a *scheduler*, not a worker: it only enqueues
``check_for_new_filings`` on schedule, it never executes any task body
itself. It MUST run as a separate process/container from the task worker(s)
(``celery -A apps.api.tasks.scheduler beat``, distinct from
``celery -A ... worker``) — see docker-compose.yml's `celery-beat` service.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any

import structlog
from celery import Celery
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from agents.orchestrator.tasks import run_agent_task
from rag.connectors.sec_edgar import FilingMeta, SECEdgarConnector
from shared.config import Settings
from shared.models import (
    Coverage,
    CoverageStatusEnum,
    Document,
    OutputTypeEnum,
    ResearchOutput,
    TaskQueue,
    TaskStatusEnum,
)

from apps.api.services.notifications import NotificationService, smtp_config_from_settings
from apps.api.services.storage import get_storage_service
from apps.api.tasks.ingestion import ingest_document_task

logger = structlog.get_logger()
settings = Settings()

celery_app = Celery("stockanalyst", broker=settings.redis_url, backend=settings.redis_url)

# 6am daily. The literal schedule lives in celery_config.py's beat_schedule
# (Celery Beat reads crontab() objects, not this string) -- kept here as the
# single source of truth for what that crontab is supposed to encode.
EARNINGS_MONITOR_SCHEDULE = "0 6 * * *"

_engine = create_async_engine(settings.get_db_url(), pool_pre_ping=True, echo=False)
_AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)

_MONITORED_FORM_TYPES = ("10-Q", "10-K")
_INGEST_TIMEOUT_SECONDS = 900


@celery_app.task(name="apps.api.tasks.scheduler.check_for_new_filings")
def check_for_new_filings() -> None:
    asyncio.run(_check_for_new_filings())


async def _check_for_new_filings() -> None:
    async with _AsyncSessionLocal() as session:
        coverages = (
            (
                await session.execute(
                    select(Coverage).where(Coverage.status == CoverageStatusEnum.active)
                )
            )
            .scalars()
            .all()
        )
        # Copy out just what's needed -- the ORM objects themselves don't
        # survive past this session's scope.
        targets = [(str(c.id), str(c.tenant_id), c.ticker, c.last_updated) for c in coverages]

    storage = get_storage_service()
    sec = SECEdgarConnector(minio_storage=storage)

    for coverage_id, tenant_id, ticker, last_updated in targets:
        try:
            await _check_coverage(sec, coverage_id, tenant_id, ticker, last_updated)
        except Exception as exc:  # noqa: BLE001 - one coverage's failure must not stop the daily sweep
            logger.warning(
                "scheduler.check_failed", coverage_id=coverage_id, ticker=ticker, error=str(exc)
            )


async def _check_coverage(
    sec: SECEdgarConnector,
    coverage_id: str,
    tenant_id: str,
    ticker: str,
    last_updated: datetime | None,
) -> None:
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            existing_urls = set(
                (
                    await session.execute(
                        select(Document.source_url).where(
                            Document.coverage_id == uuid.UUID(coverage_id)
                        )
                    )
                )
                .scalars()
                .all()
            )

    cutoff = last_updated.date() if last_updated is not None else None

    for form_type in _MONITORED_FORM_TYPES:
        try:
            filings = await sec.list_filings(ticker, form_type, years=1)
        except Exception as exc:  # noqa: BLE001 - EDGAR down for one form type shouldn't skip the other
            logger.warning(
                "scheduler.list_filings_failed", ticker=ticker, form_type=form_type, error=str(exc)
            )
            continue

        new_filing = next(
            (
                f
                for f in filings
                if f.primary_document_url not in existing_urls
                and (cutoff is None or f.filed_date > cutoff)
            ),
            None,
        )
        if new_filing is None:
            continue

        logger.info("scheduler.new_filing_found", ticker=ticker, form_type=form_type, filed_date=str(new_filing.filed_date))
        await _ingest_and_monitor(sec, new_filing, coverage_id, tenant_id, ticker)
        # One new filing per sweep is enough to trigger the earnings-monitor
        # pipeline for this coverage; a second one (e.g. both a 10-Q and an
        # 8-K landing the same day) is picked up on tomorrow's run.
        return


async def _ingest_and_monitor(
    sec: SECEdgarConnector, filing: FilingMeta, coverage_id: str, tenant_id: str, ticker: str
) -> None:
    download = await sec.download_to_minio(filing, tenant_id, coverage_id)
    if not download.download_success:
        logger.warning("scheduler.download_failed", ticker=ticker, error=download.error)
        return

    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            document = Document(
                id=uuid.uuid4(),
                coverage_id=uuid.UUID(coverage_id),
                tenant_id=uuid.UUID(tenant_id),
                file_name=download.minio_path.rsplit("/", 1)[-1],
                filing_type=filing.form_type,
                period=filing.period_of_report,
                source="sec_edgar",
                source_url=filing.primary_document_url,
                storage_path=download.minio_path,
            )
            session.add(document)
            await session.flush()
            document_id = document.id

    async_ingest_result = ingest_document_task.apply_async(
        args=[str(document_id), coverage_id, tenant_id]
    )
    # `disable_sync_subtasks=False`: this call runs inside another Celery
    # task's worker process (not the request/response path), so blocking
    # here for ingestion to actually finish before dispatching the Earnings
    # Monitor agent -- which needs the filing's chunks already indexed to
    # retrieve prior-guidance/current-results context -- is the whole point,
    # not a deadlock risk.
    await asyncio.to_thread(
        async_ingest_result.get, timeout=_INGEST_TIMEOUT_SECONDS, disable_sync_subtasks=False
    )

    await _dispatch_earnings_monitor(document_id, coverage_id, tenant_id)


async def _dispatch_earnings_monitor(document_id: uuid.UUID, coverage_id: str, tenant_id: str) -> None:
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            task = TaskQueue(
                tenant_id=uuid.UUID(tenant_id),
                coverage_id=uuid.UUID(coverage_id),
                task_type="earnings_monitor.default",
                status=TaskStatusEnum.queued,
            )
            session.add(task)
            await session.flush()
            task_id = str(task.id)

    async_result = run_agent_task.apply_async(
        args=[task_id, "earnings_monitor", "default", {"new_document_id": str(document_id)}],
        link=notify_earnings_complete_task.s(task_id, tenant_id),
    )

    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})
            task_row = await session.get(TaskQueue, uuid.UUID(task_id))
            if task_row is not None:
                task_row.celery_task_id = async_result.id


@celery_app.task(name="apps.api.tasks.scheduler.notify_earnings_complete_task")
def notify_earnings_complete_task(_run_agent_task_result: Any, task_id: str, tenant_id: str) -> None:
    """Celery `link` callback -- fires automatically once the earnings_monitor
    `run_agent_task` this was attached to succeeds. `_run_agent_task_result`
    is whatever that task returned (always None today; accepted positionally
    because Celery's `link` mechanism always prepends the parent's result).
    """
    asyncio.run(_notify_earnings_complete(task_id, tenant_id))


async def _notify_earnings_complete(task_id: str, tenant_id: str) -> None:
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})

            task = await session.get(TaskQueue, uuid.UUID(task_id))
            if task is None or task.status != TaskStatusEnum.completed or task.coverage_id is None:
                return

            result = task.result or {}
            if not result.get("approved_by_enforcer"):
                return  # rejected/partial output -- nothing worth notifying analysts about

            coverage = await session.get(Coverage, task.coverage_id)
            if coverage is None:
                return

            output = (
                await session.execute(
                    select(ResearchOutput)
                    .where(
                        ResearchOutput.coverage_id == coverage.id,
                        ResearchOutput.output_type == OutputTypeEnum.quarterly_update,
                    )
                    .order_by(ResearchOutput.generated_at.desc())
                    .limit(1)
                )
            ).scalars().first()
            if output is None:
                return

            service = NotificationService(
                redis_url=settings.redis_url, smtp_config=smtp_config_from_settings(settings)
            )
            await service.notify_earnings_complete(
                coverage={
                    "id": coverage.id,
                    "ticker": coverage.ticker,
                    "company_name": coverage.company_name,
                },
                output={"id": output.id},
                tenant_id=tenant_id,
                db=session,
            )
