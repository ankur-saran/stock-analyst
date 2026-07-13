"""
MinIO object-storage service.

All I/O methods are async — they wrap the synchronous MinIO client in
asyncio.to_thread() so they never block the FastAPI event loop.
"""
from __future__ import annotations

import asyncio
import io
from datetime import timedelta
from functools import lru_cache
from urllib.parse import urlparse

import structlog
from minio import Minio
from minio.error import S3Error

from shared.config import Settings

logger = structlog.get_logger()


class StorageService:
    """Async wrapper around the synchronous MinIO Python client."""

    def __init__(self, endpoint: str, access_key: str, secret_key: str) -> None:
        # endpoint may be "http://localhost:9000" — strip scheme for MinIO client
        parsed = urlparse(endpoint)
        minio_endpoint = parsed.netloc  # "localhost:9000"
        secure = parsed.scheme == "https"
        self._client = Minio(
            minio_endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _validate_tenant_path(self, tenant_id: str, object_path: str) -> None:
        """Raise ValueError if object_path does not belong to tenant_id."""
        expected_prefix = f"stocks-{tenant_id}/"
        if not object_path.startswith(expected_prefix):
            raise ValueError(
                f"object_path '{object_path}' does not belong to tenant '{tenant_id}'"
            )

    def _split_path(self, object_path: str) -> tuple[str, str]:
        """Return (bucket_name, object_key) from a full object_path."""
        bucket, _, key = object_path.partition("/")
        return bucket, key

    # ── Public API ────────────────────────────────────────────────────────────

    async def upload_file(
        self,
        tenant_id: str,
        coverage_id: str,
        file_type: str,
        file_name: str,
        content: bytes,
    ) -> str:
        """Upload bytes and return the canonical object_path.

        Path format: stocks-{tenant_id}/{file_type}/{coverage_id}/{file_name}
        """
        bucket = f"stocks-{tenant_id}"
        key = f"{file_type}/{coverage_id}/{file_name}"
        object_path = f"{bucket}/{key}"

        logger.info("storage.upload", bucket=bucket, key=key, bytes=len(content))
        await asyncio.to_thread(
            self._client.put_object,
            bucket,
            key,
            io.BytesIO(content),
            len(content),
        )
        return object_path

    async def get_presigned_url(
        self,
        tenant_id: str,
        object_path: str,
        expires_minutes: int = 15,
    ) -> str:
        """Return a presigned GET URL valid for expires_minutes.

        Raises ValueError if object_path belongs to a different tenant.
        """
        self._validate_tenant_path(tenant_id, object_path)
        bucket, key = self._split_path(object_path)

        logger.info(
            "storage.presign", bucket=bucket, key=key, expires_minutes=expires_minutes
        )
        url: str = await asyncio.to_thread(
            self._client.presigned_get_object,
            bucket,
            key,
            expires=timedelta(minutes=expires_minutes),
        )
        return url

    async def delete_file(self, tenant_id: str, object_path: str) -> None:
        """Delete an object.

        Raises ValueError if object_path belongs to a different tenant.
        """
        self._validate_tenant_path(tenant_id, object_path)
        bucket, key = self._split_path(object_path)

        logger.info("storage.delete", bucket=bucket, key=key)
        await asyncio.to_thread(self._client.remove_object, bucket, key)

    async def file_exists(self, object_path: str) -> bool:
        """Return True if the object exists, False on S3Error (e.g. 404)."""
        bucket, key = self._split_path(object_path)
        try:
            await asyncio.to_thread(self._client.stat_object, bucket, key)
            return True
        except S3Error:
            return False


# ── FastAPI dependency injection ──────────────────────────────────────────────


@lru_cache(maxsize=1)
def get_storage_service() -> StorageService:
    """Singleton factory for use with FastAPI Depends(). Reads Settings once."""
    settings = Settings()
    return StorageService(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password.get_secret_value(),
    )
