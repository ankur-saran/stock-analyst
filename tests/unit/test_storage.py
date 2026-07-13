"""Unit tests for StorageService — no live MinIO required."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from apps.api.services.storage import StorageService

# ── Constants ─────────────────────────────────────────────────────────────────

TENANT_ID = "00000000-0000-0000-0000-000000000001"
OTHER_TENANT_ID = "00000000-0000-0000-0000-000000000002"
COVERAGE_ID = "cov-abc123"
FILE_TYPE = "raw"
FILE_NAME = "report.pdf"
CONTENT = b"hello world"


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_minio_client() -> MagicMock:
    """Patch Minio at the module level so no real connection is attempted."""
    with patch("apps.api.services.storage.Minio") as mock_cls:
        yield mock_cls.return_value


@pytest.fixture()
def storage(mock_minio_client: MagicMock) -> StorageService:
    """StorageService backed by a mocked MinIO client."""
    return StorageService(
        endpoint="http://localhost:9000",
        access_key="minioadmin",
        secret_key="changeme",
    )


# ── Test 1: upload_file path ──────────────────────────────────────────────────


async def test_upload_file_returns_correct_path(
    storage: StorageService,
    mock_minio_client: MagicMock,
) -> None:
    result = await storage.upload_file(
        TENANT_ID, COVERAGE_ID, FILE_TYPE, FILE_NAME, CONTENT
    )
    expected = f"stocks-{TENANT_ID}/{FILE_TYPE}/{COVERAGE_ID}/{FILE_NAME}"
    assert result == expected
    mock_minio_client.put_object.assert_called_once()


# ── Test 2: get_presigned_url tenant isolation ────────────────────────────────


async def test_get_presigned_url_raises_for_wrong_tenant(
    storage: StorageService,
) -> None:
    wrong_path = f"stocks-{OTHER_TENANT_ID}/{FILE_TYPE}/{COVERAGE_ID}/{FILE_NAME}"
    with pytest.raises(ValueError, match=OTHER_TENANT_ID):
        await storage.get_presigned_url(TENANT_ID, wrong_path)


async def test_get_presigned_url_returns_url_for_correct_tenant(
    storage: StorageService,
    mock_minio_client: MagicMock,
) -> None:
    object_path = f"stocks-{TENANT_ID}/{FILE_TYPE}/{COVERAGE_ID}/{FILE_NAME}"
    mock_minio_client.presigned_get_object.return_value = "http://localhost:9000/signed"

    url = await storage.get_presigned_url(TENANT_ID, object_path)

    assert url == "http://localhost:9000/signed"
    mock_minio_client.presigned_get_object.assert_called_once()


# ── Test 3: delete_file tenant isolation ─────────────────────────────────────


async def test_delete_file_raises_for_wrong_tenant(
    storage: StorageService,
) -> None:
    wrong_path = f"stocks-{OTHER_TENANT_ID}/{FILE_TYPE}/{COVERAGE_ID}/{FILE_NAME}"
    with pytest.raises(ValueError, match=OTHER_TENANT_ID):
        await storage.delete_file(TENANT_ID, wrong_path)


async def test_delete_file_calls_remove_for_correct_tenant(
    storage: StorageService,
    mock_minio_client: MagicMock,
) -> None:
    object_path = f"stocks-{TENANT_ID}/{FILE_TYPE}/{COVERAGE_ID}/{FILE_NAME}"
    await storage.delete_file(TENANT_ID, object_path)
    mock_minio_client.remove_object.assert_called_once()


# ── Test 4: file_exists ───────────────────────────────────────────────────────


async def test_file_exists_returns_true_when_stat_succeeds(
    storage: StorageService,
    mock_minio_client: MagicMock,
) -> None:
    mock_minio_client.stat_object.return_value = MagicMock()
    object_path = f"stocks-{TENANT_ID}/{FILE_TYPE}/{COVERAGE_ID}/{FILE_NAME}"

    assert await storage.file_exists(object_path) is True


async def test_file_exists_returns_false_when_s3error(
    storage: StorageService,
    mock_minio_client: MagicMock,
) -> None:
    from minio.error import S3Error

    mock_response = MagicMock()
    mock_response.status = 404
    mock_minio_client.stat_object.side_effect = S3Error(
        "NoSuchKey",
        "The specified key does not exist.",
        "/bucket/key",
        "request-id-123",
        "host-id-abc",
        mock_response,
    )
    object_path = f"stocks-{TENANT_ID}/{FILE_TYPE}/{COVERAGE_ID}/{FILE_NAME}"

    assert await storage.file_exists(object_path) is False
