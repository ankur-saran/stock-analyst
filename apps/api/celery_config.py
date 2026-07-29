"""Celery Beat schedule for apps.api.tasks.scheduler.

Beat is a separate long-running process from the task worker(s) — it never
executes a task body itself, it only enqueues ``check_for_new_filings`` onto
the same Redis broker every worker is already listening on. Run it with:

    celery -A apps.api.celery_config:celery_app beat --loglevel=info

against the same broker/backend the workers use (`apps.api.tasks.scheduler`,
`apps.api.tasks.ingestion`, and `agents.orchestrator.tasks` all construct a
`Celery("stockanalyst", broker=settings.redis_url, ...)` app with the same
name/broker, so tasks registered on any of them are visible to a worker
started against any one of these modules). See docker-compose.yml for the
`celery-worker` / `celery-beat` service split.
"""
from __future__ import annotations

from celery.schedules import crontab

from apps.api.tasks.scheduler import celery_app

beat_schedule = {
    "check-new-filings-daily": {
        "task": "apps.api.tasks.scheduler.check_for_new_filings",
        "schedule": crontab(hour=6, minute=0),
    }
}

celery_app.conf.beat_schedule = beat_schedule
celery_app.conf.timezone = "UTC"
