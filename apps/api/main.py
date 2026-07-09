from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from shared.config import Settings
from .db import engine
from .middleware.tenant import TenantMiddleware
from .routers import admin, coverages, documents, health, outputs, tasks

settings = Settings()
logger = structlog.get_logger()

_CORS_ORIGINS = (
    ["*"] if settings.environment == "development"
    else ["http://localhost:3000"]
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: verify DB reachability
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("startup.db", status="ok")
    except Exception as exc:
        logger.error("startup.db", status="error", error=str(exc))

    logger.info("startup.complete", environment=settings.environment)
    yield

    # Shutdown: release connection pool
    await engine.dispose()
    logger.info("shutdown.complete")


def _create_app() -> FastAPI:
    is_prod = settings.environment == "production"
    app = FastAPI(
        title="Stock Analyst AI API",
        version="1.0.0",
        docs_url=None if is_prod else "/docs",
        redoc_url=None if is_prod else "/redoc",
        openapi_url=None if is_prod else "/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TenantMiddleware)

    app.include_router(health.router)
    app.include_router(coverages.router)
    app.include_router(documents.router)
    app.include_router(tasks.router)
    app.include_router(outputs.router)
    app.include_router(admin.router)

    return app


app = _create_app()
