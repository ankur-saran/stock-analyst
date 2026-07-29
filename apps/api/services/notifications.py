"""In-app + optional-email notifications, backed by Redis.

Two Redis structures per tenant/user, deliberately kept separate:

- Pub/sub channel ``notifications:{tenant_id}`` — fire-and-forget broadcast
  for any live subscriber (e.g. a future SSE/WebSocket bridge); nothing
  persists here, matching the pattern ``StreamingService`` already uses for
  task progress events.
- Sorted set ``user_notifications:{user_id}`` (``ZADD ts notification_json``)
  — the actual durable per-user inbox the REST endpoints below read from.
  Score is the unix timestamp so the set is naturally ordered oldest-to-
  newest; each member JSON-encodes its own ``id``/``read`` fields since
  Redis sorted sets have no concept of partial member updates — "marking
  read" means removing the old member and re-adding an edited copy at the
  same score.
"""
from __future__ import annotations

import json
import smtplib
import uuid
from asyncio import to_thread
from datetime import datetime, timezone
from email.message import EmailMessage
from typing import Any

import redis.asyncio as aioredis
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import Settings
from shared.models import User, UserRoleEnum

logger = structlog.get_logger()

# Oldest notifications past this count are trimmed on every write so the
# sorted set can't grow unbounded for a long-lived tenant.
_MAX_NOTIFICATIONS_PER_USER = 200
_NOTIFY_ROLES = (UserRoleEnum.analyst, UserRoleEnum.senior_analyst)


def smtp_config_from_settings(settings: Settings) -> dict[str, Any] | None:
    """Shared by the notifications router and the earnings-monitor scheduler
    task so both build the same dict shape from the same env-backed Settings
    fields rather than duplicating the mapping.
    """
    if not settings.smtp_host:
        return None
    return {
        "host": settings.smtp_host,
        "port": settings.smtp_port,
        "username": settings.smtp_username,
        "password": settings.smtp_password.get_secret_value(),
        "from_addr": settings.smtp_from_addr,
        "use_tls": settings.smtp_use_tls,
    }


class NotificationService:
    def __init__(self, redis_url: str, smtp_config: dict[str, Any] | None = None) -> None:
        self.redis = aioredis.from_url(redis_url)
        self.smtp = smtp_config

    async def notify_earnings_complete(
        self, coverage: dict[str, Any], output: dict[str, Any], tenant_id: str, db: AsyncSession
    ) -> None:
        recipients = (
            (
                await db.execute(
                    select(User).where(User.tenant_id == uuid.UUID(tenant_id), User.role.in_(_NOTIFY_ROLES))
                )
            )
            .scalars()
            .all()
        )
        if not recipients:
            return

        notification = {
            "id": str(uuid.uuid4()),
            "type": "earnings_complete",
            "ticker": coverage["ticker"],
            "coverage_id": str(coverage["id"]),
            "output_id": str(output["id"]),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "read": False,
        }

        await self.redis.publish(f"notifications:{tenant_id}", json.dumps(notification))

        for user in recipients:
            await self._push_to_inbox(str(user.id), notification)

        if self.smtp and self.smtp.get("host"):
            company_name = coverage.get("company_name", coverage["ticker"])
            for user in recipients:
                await self._send_email(
                    to_addr=user.email,
                    subject=f"New quarterly analysis: {coverage['ticker']}",
                    body=(
                        f"New quarterly analysis available for {company_name} ({coverage['ticker']}).\n"
                        "Log in to view the latest earnings comparison."
                    ),
                )

    async def get_unread_notifications(self, tenant_id: str, user_id: str) -> list[dict[str, Any]]:
        raw = await self.redis.zrevrange(f"user_notifications:{user_id}", 0, -1)
        notifications = [json.loads(item) for item in raw]
        return [n for n in notifications if not n.get("read", False)]

    async def mark_read(self, user_id: str, notification_id: str) -> None:
        key = f"user_notifications:{user_id}"
        raw = await self.redis.zrange(key, 0, -1, withscores=True)
        for member, score in raw:
            notification = json.loads(member)
            if notification.get("id") != notification_id:
                continue
            if notification.get("read"):
                return
            notification["read"] = True
            async with self.redis.pipeline(transaction=True) as pipe:
                pipe.zrem(key, member)
                pipe.zadd(key, {json.dumps(notification): score})
                await pipe.execute()
            return

    # ── internals ────────────────────────────────────────────────────────────

    async def _push_to_inbox(self, user_id: str, notification: dict[str, Any]) -> None:
        key = f"user_notifications:{user_id}"
        score = datetime.now(timezone.utc).timestamp()
        async with self.redis.pipeline(transaction=True) as pipe:
            pipe.zadd(key, {json.dumps(notification): score})
            # Keep only the most recent _MAX_NOTIFICATIONS_PER_USER entries.
            pipe.zremrangebyrank(key, 0, -(_MAX_NOTIFICATIONS_PER_USER + 1))
            await pipe.execute()

    async def _send_email(self, to_addr: str, subject: str, body: str) -> None:
        assert self.smtp is not None
        try:
            await to_thread(self._send_email_sync, to_addr, subject, body)
        except Exception as exc:  # noqa: BLE001 - email failure must never break the ingestion pipeline
            logger.warning("notifications.email_failed", to=to_addr, error=str(exc))

    def _send_email_sync(self, to_addr: str, subject: str, body: str) -> None:
        assert self.smtp is not None
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.smtp.get("from_addr") or self.smtp.get("username") or "noreply@stockanalyst.ai"
        msg["To"] = to_addr
        msg.set_content(body)

        with smtplib.SMTP(self.smtp["host"], self.smtp.get("port", 587), timeout=10) as server:
            if self.smtp.get("use_tls", True):
                server.starttls()
            username = self.smtp.get("username")
            password = self.smtp.get("password")
            if username and password:
                server.login(username, password)
            server.send_message(msg)
