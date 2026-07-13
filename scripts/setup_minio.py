"""
MinIO bucket-provisioning script for the Stock Analyst AI dev environment.

Creates two per-tenant buckets and a shared 'models' bucket, each with
virtual-folder markers (zero-byte .keep objects). Safe to run repeatedly.

Usage:
    python scripts/setup_minio.py           # skip buckets that already exist
    python scripts/setup_minio.py --force   # delete and recreate all buckets

Requires: pip install minio
"""
from __future__ import annotations

import io
import os
import sys
from urllib.parse import urlparse

# Make `shared` importable without a pip install (mirrors seed_dev.py pattern)
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), "..", "packages", "shared", "src"),
)

try:
    from minio import Minio
    from minio.error import S3Error
except ImportError:
    sys.exit("minio package not found — run: pip install 'minio>=7'")

from shared.config import Settings

# ── Constants ─────────────────────────────────────────────────────────────────

_TENANT_BUCKETS: list[tuple[str, list[str]]] = [
    (
        "stocks-00000000-0000-0000-0000-000000000001",
        ["raw", "processed"],
    ),
    (
        "stocks-00000000-0000-0000-0000-000000000002",
        ["raw", "processed"],
    ),
]

_SHARED_BUCKETS: list[tuple[str, list[str]]] = [
    ("models", []),
]

_SEP = "─" * 62


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_client(settings: Settings) -> Minio:
    parsed = urlparse(settings.minio_endpoint)
    endpoint = parsed.netloc  # strip "http://" → "localhost:9000"
    secure = parsed.scheme == "https"
    return Minio(
        endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password.get_secret_value(),
        secure=secure,
    )


def _put_keep(client: Minio, bucket: str, folder: str) -> None:
    """Place a zero-byte .keep object to represent a virtual folder."""
    client.put_object(bucket, f"{folder}/.keep", io.BytesIO(b""), 0)


def _ensure_bucket(
    client: Minio,
    bucket: str,
    folders: list[str],
    force: bool,
) -> None:
    exists = client.bucket_exists(bucket)

    if exists and not force:
        print(f"  SKIP      {bucket}  (already exists; pass --force to recreate)")
        return

    if exists and force:
        print(f"  REMOVING  {bucket} …")
        objects = list(client.list_objects(bucket, recursive=True))
        for obj in objects:
            if obj.object_name:
                client.remove_object(bucket, obj.object_name)
        client.remove_bucket(bucket)

    client.make_bucket(bucket)
    for folder in folders:
        _put_keep(client, bucket, folder)

    action = "RECREATED" if (exists and force) else "CREATED  "
    print(f"  {action} {bucket}")
    if folders:
        for folder in folders:
            print(f"             ↳ {folder}/.keep")


# ── Entry point ───────────────────────────────────────────────────────────────


def setup(force: bool = False) -> None:
    settings = Settings()
    client = _make_client(settings)

    print(f"\n{_SEP}")
    print("  MinIO bucket setup")
    print(f"  Endpoint : {settings.minio_endpoint}")
    print(f"  Force    : {force}")
    print(_SEP)

    print("\nTENANT BUCKETS")
    for bucket, folders in _TENANT_BUCKETS:
        _ensure_bucket(client, bucket, folders, force)

    print("\nSHARED BUCKETS")
    for bucket, folders in _SHARED_BUCKETS:
        _ensure_bucket(client, bucket, folders, force)

    print(f"\n{_SEP}")
    print("  Done.")
    print(f"{_SEP}\n")


if __name__ == "__main__":
    _force = "--force" in sys.argv
    setup(force=_force)
