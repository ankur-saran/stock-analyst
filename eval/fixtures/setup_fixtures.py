"""Reproducibly (re)builds every eval fixture coverage.

Run before every eval pass (this is exactly what the ``eval-gate`` CI job
does): deletes the eval tenant's existing coverages -- Postgres rows via
cascade, plus their Qdrant vectors, which Postgres cascade never touches --
then recreates each coverage in ``fixture_content.FIXTURE_COVERAGES`` from
scratch and re-ingests its synthetic PDFs through the exact same
parse -> chunk -> embed -> index pipeline ``apps.api.tasks.ingestion`` runs
for a real upload. Running it twice in a row must produce byte-identical
*content* (new UUIDs each time, but the same documents, chunk counts, and
indexed text) -- that's what "reproducible" means for an eval fixture: no
leftover state from a prior run's LLM output or a partially-applied dataset
change can leak into the next eval run.

``users``/``coverages``/``documents`` all carry the ``tenant_isolation`` RLS
policy from migration 001, so every transaction here -- exactly like
``apps.api.tasks.ingestion`` and ``apps.api.routers.tasks`` -- opens with
``SET LOCAL app.current_tenant_id`` before touching any of them; skipping it
doesn't error, it just silently sees zero rows.

This script does *not* create a matching Keycloak user -- like
``scripts/seed_dev.py``, it only touches Postgres/MinIO/Qdrant. Instead, the
eval tenant's id defaults to ``00000000-0000-0000-0000-000000000001``, the
same fixed id ``infra/keycloak/realm-export.json`` already assigns (via its
``tenant_id`` attribute) to the pre-seeded ``analyst-a`` user, so a real
bearer token for that user authorizes against these fixture coverages
without any extra Keycloak configuration. Override with the
``EVAL_TENANT_ID`` env var if a different tenant/token pairing is in use.
``eval/runners/run_eval.py`` expects that token via ``--token`` or
``EVAL_BEARER_TOKEN`` -- see its module docstring for why it can't just mint
one itself (``stock-analyst-api``'s service account has no ``tenant_id``
claim mapper, and direct-access-grants are off for both realm clients).

Usage:
    python -m eval.fixtures.setup_fixtures
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from rag.connectors.qdrant_client import QdrantConnector
from rag.ingestion.chunkers.hierarchical import HierarchicalChunker
from rag.ingestion.parsers.pdf_parser import PDFParser
from rag.ingestion.parsers.table_extractor import TableExtractor
from rag.ingestion.pipeline import EmbeddingPipeline
from shared.config import Settings
from shared.models import (
    Coverage,
    CoverageStatusEnum,
    Document,
    Industry,
    IngestStatusEnum,
    PlanEnum,
    Tenant,
    User,
    UserRoleEnum,
)

from apps.api.services.storage import StorageService

from eval.fixtures.fixture_content import FIXTURE_COVERAGES, FIXTURE_DOCUMENTS
from eval.fixtures.pdf_builder import build_all_fixture_pdfs

_EVAL_TENANT_NAME = "Eval Fixtures"
_EVAL_USER_EMAIL = "eval-runner@stockanalyst.internal"
# Matches the `tenant_id` attribute on the `analyst-a` user in
# infra/keycloak/realm-export.json -- see module docstring.
_DEFAULT_EVAL_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_QDRANT_COLLECTION_PREFIX = "tenant"
_MANIFEST_PATH = Path(__file__).parent / "manifest.json"
_DOCUMENTS_DIR = Path(__file__).parent / "documents"


async def _set_tenant(session: AsyncSession, tenant_id: str) -> None:
    await session.execute(text("SET LOCAL app.current_tenant_id = :tid"), {"tid": tenant_id})


async def setup_fixtures() -> dict[str, Any]:
    settings = Settings()
    engine = create_async_engine(settings.get_db_url(), echo=False)

    build_all_fixture_pdfs(_DOCUMENTS_DIR)

    storage = StorageService(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_root_user,
        secret_key=settings.minio_root_password.get_secret_value(),
    )
    raw_qdrant = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    qdrant = QdrantConnector(host=settings.qdrant_host, port=settings.qdrant_port, client=raw_qdrant)
    embedder = EmbeddingPipeline(ollama_url=settings.ollama_base_url, qdrant_client=raw_qdrant)

    try:
        async with AsyncSession(engine, expire_on_commit=False) as session:
            tenant = await _reset_eval_tenant(session, qdrant)
            tenant_id = str(tenant.id)
            manifest: dict[str, Any] = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "tenant_id": tenant_id,
                "coverages": {},
            }

            for label, spec in FIXTURE_COVERAGES.items():
                coverage = await _create_coverage(session, tenant_id, spec)
                doc_ids: dict[str, str] = {}
                for file_name in spec["documents"]:
                    document = await _ingest_document(
                        session, storage, embedder, tenant_id, coverage, file_name
                    )
                    doc_ids[file_name] = str(document.id)

                manifest["coverages"][label] = {
                    "coverage_id": str(coverage.id),
                    "ticker": spec["ticker"],
                    "documents": doc_ids,
                }
                print(f"  {label}: coverage={coverage.id} ({len(doc_ids)} documents indexed)")

        _MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"\nWrote manifest: {_MANIFEST_PATH}")
        return manifest
    finally:
        await engine.dispose()


def _eval_tenant_id() -> uuid.UUID:
    override = os.environ.get("EVAL_TENANT_ID")
    return uuid.UUID(override) if override else _DEFAULT_EVAL_TENANT_ID


async def _reset_eval_tenant(session: AsyncSession, qdrant: QdrantConnector) -> Tenant:
    # `tenants` itself carries no tenant_id column and isn't RLS-protected.
    tenant_id = _eval_tenant_id()
    existing = await session.get(Tenant, tenant_id)

    if existing is not None:
        tenant_id_str = str(tenant_id)
        async with session.begin():
            await _set_tenant(session, tenant_id_str)
            coverage_ids = (
                await session.execute(select(Coverage.id).where(Coverage.tenant_id == tenant_id))
            ).scalars().all()

        collection = f"{_QDRANT_COLLECTION_PREFIX}_{tenant_id_str}"
        for coverage_id in coverage_ids:
            await qdrant.delete_by_filter(
                collection=collection,
                filter_={"must": [{"key": "coverage_id", "match": {"value": str(coverage_id)}}]},
            )

        async with session.begin():
            await _set_tenant(session, tenant_id_str)
            await session.delete(existing)  # cascades coverages/documents/research_outputs/task_queue

    async with session.begin():
        tenant = Tenant(id=tenant_id, name=_EVAL_TENANT_NAME, plan=PlanEnum.enterprise)
        session.add(tenant)
        await session.flush()
        await _set_tenant(session, str(tenant.id))
        session.add(User(tenant_id=tenant.id, email=_EVAL_USER_EMAIL, role=UserRoleEnum.analyst))
    return tenant


async def _get_or_create_industry(session: AsyncSession, name: str) -> Industry:
    # `industries` has no tenant_id column and isn't RLS-protected.
    existing = (
        await session.execute(select(Industry).where(Industry.name == name))
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    async with session.begin():
        industry = Industry(name=name)
        session.add(industry)
        await session.flush()
    return industry


async def _create_coverage(session: AsyncSession, tenant_id: str, spec: dict[str, Any]) -> Coverage:
    industry_id = None
    if spec.get("industry_name"):
        industry = await _get_or_create_industry(session, spec["industry_name"])
        industry_id = industry.id

    async with session.begin():
        await _set_tenant(session, tenant_id)
        user = (
            await session.execute(select(User).where(User.tenant_id == tenant_id))
        ).scalars().first()

        coverage = Coverage(
            tenant_id=tenant_id,
            ticker=spec["ticker"],
            company_name=spec["company_name"],
            exchange=spec["exchange"],
            industry_id=industry_id,
            created_by=user.id,
            status=CoverageStatusEnum.active,
            document_count=0,
        )
        session.add(coverage)
        await session.flush()
    return coverage


async def _ingest_document(
    session: AsyncSession,
    storage: StorageService,
    embedder: EmbeddingPipeline,
    tenant_id: str,
    coverage: Coverage,
    file_name: str,
) -> Document:
    """Run the exact parse -> chunk -> embed -> index pipeline synchronously.

    Mirrors ``apps.api.tasks.ingestion._run_ingestion`` but skips Celery and
    the duplicate-file-hash check entirely -- fixtures are always freshly
    (re)created by ``_reset_eval_tenant`` first, so there is never a prior
    document to collide with.
    """
    spec = FIXTURE_DOCUMENTS[file_name]
    pdf_path = _DOCUMENTS_DIR / file_name
    content = pdf_path.read_bytes()

    storage_path = await storage.upload_file(tenant_id, str(coverage.id), "raw", file_name, content)

    async with session.begin():
        await _set_tenant(session, tenant_id)
        document = Document(
            coverage_id=coverage.id,
            tenant_id=tenant_id,
            file_name=file_name,
            filing_type=spec["filing_type"],
            period=spec["period"],
            source="eval_fixture",
            storage_path=storage_path,
            ingest_status=IngestStatusEnum.pending,
        )
        session.add(document)
        await session.flush()
        document_id = document.id

    parsed_doc = PDFParser().parse(pdf_path, str(document_id), file_name)
    tables = TableExtractor().extract_tables(
        pdf_path, parsed_doc, str(document_id), spec["filing_type"], spec["period"]
    )
    chunks = HierarchicalChunker().chunk_document(
        parsed_doc,
        tables,
        tenant_id,
        str(coverage.id),
        filing_type=spec["filing_type"],
        period=spec["period"],
        document_name=file_name,
    )
    indexed_points = await embedder.index_chunks(chunks, tenant_id)
    searchable_count = sum(1 for c in chunks if c.chunk_type in ("child", "table"))

    async with session.begin():
        await _set_tenant(session, tenant_id)
        document = await session.get(Document, document_id)
        document.ingest_status = IngestStatusEnum.indexed
        document.chunk_count = searchable_count
        document.page_count = parsed_doc.total_pages
        document.quality_score = parsed_doc.overall_text_coverage
        document.ingested_at = datetime.now(timezone.utc)

        coverage_row = await session.get(Coverage, coverage.id)
        coverage_row.document_count += 1
        coverage_row.last_updated = datetime.now(timezone.utc)

    print(f"    {file_name}: {searchable_count} searchable chunks, {indexed_points} points indexed")
    return document


if __name__ == "__main__":
    asyncio.run(setup_fixtures())
