"""
Qdrant reindex script — rebuilds vector-store entries for documents whose
Postgres/MinIO data is intact but whose Qdrant points are gone or suspect
(see docs/disaster-recovery.md, Scenario 5: Qdrant Vector Store Corruption).

Re-enqueues ingest_document_task for every matching Document. That task
downloads the original file from MinIO (storage_path is untouched — Qdrant
loss doesn't touch object storage), re-parses, re-chunks and re-embeds it.
It is safe to re-run against a document that already ingested successfully:
apps/api/tasks/ingestion.py's duplicate check excludes the document's own id
(`Document.id != doc_uuid`), so re-ingesting a document against itself is
never flagged as a dupe — it just re-embeds and overwrites that document's
Qdrant points.

Like scripts/seed_dev.py, this connects directly with no
`SET app.current_tenant_id` — it relies on the connecting Postgres role
bypassing RLS (POSTGRES_USER is a superuser under the stock postgres:16
image; see the caveat in infra/scripts/security_audit.sh's header comment).
Enqueuing goes through the real Celery broker (Redis), not a direct
function call, so REDIS_URL must point at a reachable broker — port-forward
it first if running from outside the cluster, the same way
infra/k8s/scripts/bootstrap.sh port-forwards MinIO for scripts/setup_minio.py.

Usage (from the project root):
    python scripts/reindex_all.py                          # every document, every tenant
    python scripts/reindex_all.py --coverage-id <uuid>      # just one coverage
    python scripts/reindex_all.py --dry-run                 # list what would be enqueued
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(__file__) + "/..")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "shared", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "rag", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "packages", "agents", "src"))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared.config import Settings
from shared.models import Document

from apps.api.tasks.ingestion import ingest_document_task  # noqa: E402  (needs sys.path set up first)


async def _fetch_documents(coverage_id: str | None) -> list[Document]:
    settings = Settings()
    engine = create_async_engine(settings.get_db_url(), echo=False)
    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            stmt = select(Document)
            if coverage_id:
                stmt = stmt.where(Document.coverage_id == uuid.UUID(coverage_id))
            return (await session.execute(stmt)).scalars().all()
    finally:
        await engine.dispose()


def reindex(coverage_id: str | None, dry_run: bool) -> None:
    documents = asyncio.run(_fetch_documents(coverage_id))

    if not documents:
        scope = f"coverage {coverage_id}" if coverage_id else "any coverage"
        print(f"No documents found for {scope}. Nothing to do.")
        return

    print(f"Found {len(documents)} document(s) to reindex.")
    for doc in documents:
        if dry_run:
            print(f"  DRY-RUN  document={doc.id} coverage={doc.coverage_id} tenant={doc.tenant_id}")
            continue
        ingest_document_task.delay(
            document_id=str(doc.id),
            coverage_id=str(doc.coverage_id),
            tenant_id=str(doc.tenant_id),
        )
        print(f"  ENQUEUED document={doc.id} coverage={doc.coverage_id} tenant={doc.tenant_id}")

    if not dry_run:
        print(
            f"\nEnqueued {len(documents)} ingestion task(s). Track progress via Flower "
            "or SELECT ingest_status FROM documents."
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-id", default=None, help="Limit to a single coverage's documents")
    parser.add_argument("--dry-run", action="store_true", help="List what would be enqueued without enqueuing")
    args = parser.parse_args()
    reindex(coverage_id=args.coverage_id, dry_run=args.dry_run)
