"""Re-export of the shared Redis pub/sub streaming service.

The implementation lives in ``shared.streaming`` since the Celery worker
(``packages.agents``) publishes events and must not import from ``apps.api``
-- this module just puts the class where the API layer expects to find it.
"""
from __future__ import annotations

from shared.streaming import StreamingService

__all__ = ["StreamingService"]
