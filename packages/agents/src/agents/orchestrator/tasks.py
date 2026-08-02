"""Celery entrypoint the orchestrator dispatches agent work through.

Mirrors the Celery app pattern used by ``apps.api.tasks.ingestion`` — a sync
Celery task that hands off to a single ``asyncio.run()`` call, since the
underlying agent I/O (Postgres, LiteLLM, Qdrant) is all async, and every DB
touch opens its own short-lived session that ``SET LOCAL app.current_tenant_id``
before querying a tenant-scoped table.

Agent classes are resolved lazily by dotted path rather than imported at
module load time: most of the 7 agents don't exist yet, and a bare import of
an unimplemented module would crash the whole worker before a single task
ran. ``_resolve_agent_class`` turns that into a per-task failure instead —
the ``task_queue`` row is marked ``failed`` with a clear error, nothing else
is affected.
"""
from __future__ import annotations

import asyncio
import importlib
import uuid
from datetime import datetime, timezone
from typing import Any

from celery import Celery
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from shared.config import Settings
from shared.models import OutputTypeEnum, ResearchOutput, TaskQueue, TaskStatusEnum
from shared.streaming import StreamingService

from agents.orchestrator.graph import get_retriever
from agents.shared.message import AgentMessage, AgentOutput, AgentType

settings = Settings()

celery_app = Celery(
    "stockanalyst", broker=settings.redis_url, backend=settings.redis_url
)

_engine = create_async_engine(settings.get_db_url(), pool_pre_ping=True, echo=False)
_AsyncSessionLocal = async_sessionmaker(_engine, expire_on_commit=False)

# Dotted paths, not direct imports — see module docstring. Orchestrator is
# deliberately absent: it's invoked directly from the API, never dispatched
# through this Celery path, matching `tools.list_available_agents()`.
_AGENT_REGISTRY: dict[str, str] = {
    "industry_analyst": "agents.industry_analyst.agent.IndustryAnalystAgent",
    "document_ingestion": "agents.document_ingestion.agent.DocumentIngestionAgent",
    "lynch_pitch": "agents.lynch_pitch.agent.LynchPitchAgent",
    "munger_invert": "agents.munger_invert.agent.MungerInvertAgent",
    "earnings_monitor": "agents.earnings_monitor.agent.EarningsMonitorAgent",
    "kpi_tracker": "agents.kpi_tracker.agent.KPITrackerAgent",
}

# Agents whose approved output is a citable research artifact worth persisting.
# Orchestrator/document-ingestion have no research_outputs row and are
# intentionally absent — they just don't get this extra write.
_OUTPUT_TYPE_BY_AGENT: dict[str, OutputTypeEnum] = {
    "industry_analyst": OutputTypeEnum.industry_primer,
    "lynch_pitch": OutputTypeEnum.lynch_pitch,
    "munger_invert": OutputTypeEnum.munger_invert,
    "earnings_monitor": OutputTypeEnum.quarterly_update,
    "kpi_tracker": OutputTypeEnum.kpi_snapshot,
}


@celery_app.task(bind=True, max_retries=1, name="agents.run_agent_task")  # type: ignore[misc]
def run_agent_task(self, task_id: str, agent: str, skill: str, payload: dict[str, Any]) -> None:
    asyncio.run(_execute(task_id, agent, skill, payload))


def _error_event(exc: Exception) -> dict[str, Any]:
    # "retry_count" is always 0 -- there's no retry loop anywhere in the
    # pipeline today to report a real count from.
    return {"type": "error", "code": "TASK_FAILED", "retry_count": 0, "detail": str(exc)[:500]}


async def _execute(task_id: str, agent_name: str, skill: str, payload: dict[str, Any]) -> None:
    task_uuid = uuid.UUID(task_id)
    streaming_svc = StreamingService(settings.redis_url)

    tenant_id, coverage_id = await _load_task_context(task_uuid)
    if tenant_id is None:
        return  # task_queue row vanished under us; nothing left to report against

    await _set_task_status(task_uuid, tenant_id, TaskStatusEnum.running, started_at=True)

    try:
        agent_cls = _resolve_agent_class(agent_name)
    except ValueError as exc:
        await streaming_svc.publish_event(task_id, _error_event(exc))
        await _set_task_status(
            task_uuid, tenant_id, TaskStatusEnum.failed, error=str(exc), completed_at=True
        )
        return

    try:
        output_dict = await _run_agent(
            agent_cls, agent_name, skill, payload, task_id, coverage_id, tenant_id, streaming_svc
        )
    except Exception as exc:  # noqa: BLE001 - reported via task_queue.error, not re-raised
        await streaming_svc.publish_event(task_id, _error_event(exc))
        await _set_task_status(
            task_uuid, tenant_id, TaskStatusEnum.failed, error=str(exc)[:2000], completed_at=True
        )
        return

    await _set_task_status(
        task_uuid, tenant_id, TaskStatusEnum.completed, completed_at=True, result=output_dict
    )


def _resolve_agent_class(agent_name: str) -> type:
    dotted_path = _AGENT_REGISTRY.get(agent_name)
    if dotted_path is None:
        raise ValueError(f"Unknown agent '{agent_name}' — no entry in the agent registry")

    module_path, class_name = dotted_path.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise ValueError(
            f"Agent '{agent_name}' is registered but not yet implemented ({exc})"
        ) from exc

    agent_cls = getattr(module, class_name, None)
    if agent_cls is None:
        raise ValueError(f"Module for agent '{agent_name}' does not define '{class_name}'")
    return agent_cls


def _terminal_event(output: AgentOutput) -> dict[str, Any]:
    if output.enforcer_status in ("partial", "failed"):
        # Both mean "content was saved but not fully validated" -- there's no
        # retry loop to distinguish "partial after retries exhausted" from a
        # single-shot enforcer failure, and nothing raised, so "error" would
        # be wrong here.
        return {
            "type": "partial",
            "output_id": output.message_id,
            "citation_coverage_pct": output.citation_coverage_pct,
            "reason": "Citation Enforcer did not fully approve this output — manual review recommended.",
        }
    # "approved", plus agents that don't wire the enforcer at all (their
    # AgentOutput.enforcer_status stays at the "pending" default, e.g.
    # industry_analyst) -- both resolve to "complete" so this task's lifecycle
    # is unaffected for agents this change doesn't touch.
    return {
        "type": "complete",
        "output_id": output.message_id,
        "citation_coverage_pct": output.citation_coverage_pct,
        "llm_used": output.llm_used,
    }


async def _run_agent(
    agent_cls: type,
    agent_name: str,
    skill: str,
    payload: dict[str, Any],
    task_id: str,
    coverage_id: str | None,
    tenant_id: str,
    streaming_svc: StreamingService,
) -> dict[str, Any]:
    await streaming_svc.publish_event(
        task_id,
        {"type": "progress", "step": "starting", "pct": 5, "detail": f"Running {agent_name}..."},
    )

    async with _AsyncSessionLocal() as session:
        # BaseAgent._log_audit unconditionally commits inside agent.run(), which
        # closes this block's transaction out from under it — so the
        # ResearchOutput write below must happen in a fresh `session.begin()`
        # block, not appended to this one (SQLAlchemy raises InvalidRequestError
        # if you keep using a session.begin() block after something inside it
        # already committed).
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id}
            )

            agent_instance = agent_cls(
                db_session=session,
                retriever=get_retriever(),
                streaming_svc=streaming_svc,
                task_id=task_id,
            )
            message = AgentMessage(
                sender=AgentType.ORCHESTRATOR,
                recipient=AgentType(agent_name),
                task_id=task_id,
                coverage_id=coverage_id or "",
                tenant_id=tenant_id,
                payload={**payload, "skill": skill},
            )
            output = await agent_instance.run(message)

        output_type = _OUTPUT_TYPE_BY_AGENT.get(agent_name)
        if output.approved_by_enforcer and output_type is not None and coverage_id is not None:
            async with session.begin():
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id}
                )
                session.add(
                    ResearchOutput(
                        coverage_id=uuid.UUID(coverage_id),
                        tenant_id=uuid.UUID(tenant_id),
                        output_type=output_type,
                        content=output.content,
                        citations=output.citations,
                        citation_coverage_pct=output.citation_coverage_pct,
                        approved_by_enforcer=output.approved_by_enforcer,
                        enforcer_status=output.enforcer_status,
                        llm_used=output.llm_used,
                        tokens_used=output.tokens_used,
                    )
                )

        await streaming_svc.publish_event(task_id, _terminal_event(output))
        return output.model_dump(mode="json")


async def _load_task_context(task_uuid: uuid.UUID) -> tuple[str | None, str | None]:
    """Read tenant_id/coverage_id off the task row itself.

    There's no tenant to ``SET LOCAL`` yet at this point — that's exactly the
    piece of information this query exists to produce — so it reads the row
    by primary key before any RLS scoping is possible, same as the caller
    (``orchestrator.tools.dispatch_task``) already trusted this row to exist
    when it created it.
    """
    async with _AsyncSessionLocal() as session:
        task = await session.get(TaskQueue, task_uuid)
        if task is None:
            return None, None
        return str(task.tenant_id), (str(task.coverage_id) if task.coverage_id else None)


async def _set_task_status(
    task_uuid: uuid.UUID,
    tenant_id: str,
    status: TaskStatusEnum,
    *,
    started_at: bool = False,
    completed_at: bool = False,
    error: str | None = None,
    result: dict[str, Any] | None = None,
) -> None:
    async with _AsyncSessionLocal() as session:
        async with session.begin():
            await session.execute(
                text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id}
            )
            task = await session.get(TaskQueue, task_uuid)
            if task is None:
                return
            task.status = status
            if started_at:
                task.started_at = datetime.now(timezone.utc)
            if completed_at:
                task.completed_at = datetime.now(timezone.utc)
            if error is not None:
                task.error = error
            if result is not None:
                task.result = result
