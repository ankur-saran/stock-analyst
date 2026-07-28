"""Redis pub/sub transport for live task events.

Used from two different processes: the Celery worker (``packages.agents``,
via ``BaseAgent``/``orchestrator.tasks``) publishes as an agent runs, and the
FastAPI process (``apps.api.routers.tasks``'s WebSocket endpoint) subscribes
to forward events to the browser. Lives here rather than in ``apps/api``
because both processes already depend on ``shared`` for ``config``/
``models`` and ``agents`` must never import from ``apps.api``.
"""
from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from typing import Any

import redis.asyncio as aioredis

_TERMINAL_EVENT_TYPES = frozenset({"complete", "error", "partial"})


class StreamingService:
    def __init__(self, redis_url: str) -> None:
        self.redis = aioredis.from_url(redis_url)

    async def publish_event(self, task_id: str, event: dict[str, Any]) -> None:
        channel = f"task:{task_id}"
        await self.redis.publish(channel, json.dumps(event))

    async def subscribe_events(self, task_id: str) -> AsyncGenerator[dict[str, Any], None]:
        """Yield events published for ``task_id`` until a terminal event arrives.

        Terminal types are "complete", "error", and "partial" -- all three end
        the task's lifecycle and have no further events coming.
        """
        channel = f"task:{task_id}"
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    event = json.loads(message["data"])
                    yield event
                    if event.get("type") in _TERMINAL_EVENT_TYPES:
                        break
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()
