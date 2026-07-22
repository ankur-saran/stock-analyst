"""Thin async wrapper around the (sync) Qdrant client with retries.

qdrant-client's ``QdrantClient`` is sync-only, so every call here runs on a
worker thread via ``asyncio.to_thread``. All four operations retry up to 3
times with exponential backoff — Qdrant sits behind a network hop from the
API/agent processes and transient connection errors during ingestion bursts
shouldn't fail an entire indexing run.
"""
from __future__ import annotations

import asyncio
from typing import Any

import structlog
from qdrant_client import QdrantClient, models

logger = structlog.get_logger()

_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_BACKOFF_BASE = 0.5


class QdrantConnectorError(RuntimeError):
    """Raised when a Qdrant operation keeps failing after all retries."""


class QdrantConnector:
    def __init__(
        self,
        host: str,
        port: int,
        timeout: float = 30.0,
        client: QdrantClient | None = None,
        retry_backoff_base: float = _DEFAULT_RETRY_BACKOFF_BASE,
    ) -> None:
        self._client = client or QdrantClient(host=host, port=port, timeout=int(timeout))
        self._retry_backoff_base = retry_backoff_base

    async def upsert_points(self, collection: str, points: list[models.PointStruct]) -> None:
        for i in range(0, len(points), 100):
            batch = points[i : i + 100]
            await self._with_retry(
                self._client.upsert, collection_name=collection, points=batch
            )

    async def search_dense(
        self,
        collection: str,
        query_vector: list[float],
        filter_: dict[str, Any],
        limit: int,
    ) -> list[models.ScoredPoint]:
        response = await self._with_retry(
            self._client.query_points,
            collection_name=collection,
            query=query_vector,
            using="dense",
            query_filter=self._to_filter(filter_),
            limit=limit,
        )
        return response.points

    async def search_sparse(
        self,
        collection: str,
        sparse_vector: dict[int, float],
        filter_: dict[str, Any],
        limit: int,
    ) -> list[models.ScoredPoint]:
        response = await self._with_retry(
            self._client.query_points,
            collection_name=collection,
            query=models.SparseVector(
                indices=list(sparse_vector.keys()), values=list(sparse_vector.values())
            ),
            using="sparse",
            query_filter=self._to_filter(filter_),
            limit=limit,
        )
        return response.points

    async def get_point(self, collection: str, point_id: str) -> models.Record | None:
        records = await self._with_retry(
            self._client.retrieve, collection_name=collection, ids=[point_id]
        )
        return records[0] if records else None

    async def delete_by_filter(self, collection: str, filter_: dict[str, Any]) -> None:
        await self._with_retry(
            self._client.delete,
            collection_name=collection,
            points_selector=models.FilterSelector(filter=self._to_filter(filter_)),
        )

    @staticmethod
    def _to_filter(filter_: dict[str, Any]) -> models.Filter:
        return models.Filter(**filter_)

    async def _with_retry(self, func: Any, /, *args: Any, **kwargs: Any) -> Any:
        last_error: Exception | None = None
        for attempt in range(_MAX_ATTEMPTS):
            try:
                return await asyncio.to_thread(func, *args, **kwargs)
            except Exception as exc:  # noqa: BLE001 - retried below, re-raised after exhausting attempts
                last_error = exc
                logger.warning(
                    "qdrant.request_failed",
                    attempt=attempt + 1,
                    max_attempts=_MAX_ATTEMPTS,
                    error=str(exc),
                )
                if attempt < _MAX_ATTEMPTS - 1:
                    await asyncio.sleep(self._retry_backoff_base * (2**attempt))

        raise QdrantConnectorError(
            f"Qdrant operation failed after {_MAX_ATTEMPTS} attempts"
        ) from last_error
