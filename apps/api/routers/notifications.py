"""In-app notification inbox — backs the sidebar notification bell.

No coverage/tenant nesting in the path: a user's inbox is keyed by user_id
in Redis (see services/notifications.py), so these read the caller's own
notifications directly off their JWT identity.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from shared.config import Settings

from apps.api.middleware.auth import CurrentUser, get_current_user
from apps.api.services.notifications import NotificationService, smtp_config_from_settings

router = APIRouter(prefix="/notifications", tags=["notifications"])

settings = Settings()


def get_notification_service() -> NotificationService:
    return NotificationService(redis_url=settings.redis_url, smtp_config=smtp_config_from_settings(settings))


@router.get("/unread")
async def get_unread(
    current_user: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> list[dict[str, Any]]:
    return await service.get_unread_notifications(str(current_user.tenant_id), str(current_user.user_id))


@router.post("/{notification_id}/read")
async def mark_notification_read(
    notification_id: str,
    current_user: CurrentUser = Depends(get_current_user),
    service: NotificationService = Depends(get_notification_service),
) -> dict[str, str]:
    await service.mark_read(str(current_user.user_id), notification_id)
    return {"status": "ok"}
