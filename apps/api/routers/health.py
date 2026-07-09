import asyncio
import time

import httpx
from fastapi import APIRouter
from sqlalchemy import text

from shared.config import Settings

settings = Settings()
router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": "1.0.0", "environment": settings.environment}


# ── Service checks ──────────────────────────────────────────────────────────

async def _check_postgres() -> dict:
    t0 = time.monotonic()
    try:
        from apps.api.db import engine
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return {"status": "ok", "latency_ms": _ms(t0)}
    except Exception as exc:
        return {"status": "error", "latency_ms": _ms(t0), "error": str(exc)}


async def _check_redis() -> dict:
    t0 = time.monotonic()
    try:
        import redis.asyncio as aioredis
        client = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)
        await client.ping()
        await client.aclose()
        return {"status": "ok", "latency_ms": _ms(t0)}
    except Exception as exc:
        return {"status": "error", "latency_ms": _ms(t0), "error": str(exc)}


async def _check_http(url: str) -> dict:
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return {"status": "ok", "latency_ms": _ms(t0)}
    except Exception as exc:
        return {"status": "error", "latency_ms": _ms(t0), "error": str(exc)}


async def _check_minio() -> dict:
    # MinIO exposes /minio/health/live — no credentials needed
    return await _check_http(f"{settings.minio_endpoint}/minio/health/live")


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


@router.get("/health/deep")
async def health_deep() -> dict:
    postgres, redis, qdrant, minio, litellm = await asyncio.gather(
        _check_postgres(),
        _check_redis(),
        _check_http(f"http://{settings.qdrant_host}:{settings.qdrant_port}/healthz"),
        _check_minio(),
        _check_http(f"{settings.litellm_url}/health"),
    )

    services = {
        "postgres": postgres,
        "redis": redis,
        "qdrant": qdrant,
        "minio": minio,
        "litellm": litellm,
    }

    errors = sum(1 for s in services.values() if s["status"] == "error")
    if errors == 0:
        overall = "healthy"
    elif errors <= 2:
        overall = "degraded"
    else:
        overall = "unhealthy"

    return {"status": overall, "services": services}
