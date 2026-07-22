"""Celery entrypoint the orchestrator dispatches agent work through.

Mirrors the Celery app pattern used by ``apps.api.tasks.ingestion`` — a sync
Celery task that hands off to a single ``asyncio.run()`` call, since the
underlying agent I/O (Postgres, LiteLLM, Qdrant) is all async.

Routing ``agent``/``skill`` to a concrete ``BaseAgent`` subclass is filled in
as each of the 7 agents lands; today this is the stable task signature that
``orchestrator.tools.dispatch_task`` enqueues against.
"""
from __future__ import annotations

from typing import Any

from celery import Celery

from shared.config import Settings

settings = Settings()

celery_app = Celery(
    "stockanalyst", broker=settings.redis_url, backend=settings.redis_url
)


@celery_app.task(name="agents.run_agent_task")  # type: ignore[misc]  # celery ships no decorator typing
def run_agent_task(task_id: str, agent: str, skill: str, payload: dict[str, Any]) -> None:
    raise NotImplementedError(
        f"No agent implementation registered yet for {agent}.{skill} (task_id={task_id})"
    )
