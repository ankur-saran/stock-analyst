"""Integration tests: tenant isolation across the API, Qdrant, and Postgres RLS.

Prerequisites: the same Docker Compose stack as test_full_workflow.py, but
this file only needs Postgres + Qdrant + Keycloak reachable -- no Celery
worker or LLM calls involved.

Run:
    pytest tests/integration/test_tenant_isolation.py -v -m integration
"""
from __future__ import annotations

import uuid

import httpx
import pytest
from qdrant_client import QdrantClient
from rag.connectors.qdrant_client import QdrantConnector
from rag.ingestion.chunkers.hierarchical import Chunk
from rag.ingestion.pipeline import EmbeddingPipeline
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.config import Settings
from sqlalchemy import text

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

settings = Settings()

_PASSAGE = (
    "Gross margin expanded to 45.2% in fiscal 2023, driven by favorable "
    "product mix. Total net revenue increased 8% year over year."
)


def _make_chunk(coverage_id: str, tenant_id: str) -> Chunk:
    metadata = {
        "document_id": str(uuid.uuid4()),
        "document_name": "TENANT_ISOLATION_TEST.pdf",
        "filing_type": "10-K",
        "period": "FY2023",
        "section_name": "mda",
        "tenant_id": tenant_id,
        "coverage_id": coverage_id,
        "page_number": 1,
        "chunk_type": "child",
        "parent_chunk_id": None,
        "char_start": 0,
        "char_end": len(_PASSAGE),
        "token_estimate": len(_PASSAGE.split()),
    }
    return Chunk(
        chunk_id=str(uuid.uuid4()),
        content=_PASSAGE,
        chunk_type="child",
        parent_chunk_id=None,
        metadata=metadata,
    )


async def test_api_cross_tenant_blocked(
    api_client_tenant_b: httpx.AsyncClient, tenant_a_coverage_id: str
) -> None:
    """Tenant B's client must not be able to read tenant A's coverage."""
    resp = await api_client_tenant_b.get(f"/coverages/{tenant_a_coverage_id}")
    assert resp.status_code in (403, 404), (
        f"cross-tenant API access not blocked: got {resp.status_code}"
    )


async def test_qdrant_cross_tenant_returns_zero_results(
    test_tenant_a_id: str, test_tenant_b_id: str, tenant_a_coverage_id: str
) -> None:
    """Index a real chunk under tenant A's coverage, then confirm tenant B's
    retriever call -- even handed tenant A's own coverage_id directly --
    never sees it. (A trivial "0 results" from an unindexed coverage
    wouldn't actually prove isolation; this indexes real data first.)
    """
    raw_client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    qdrant = QdrantConnector(host=settings.qdrant_host, port=settings.qdrant_port)
    embedder = EmbeddingPipeline(ollama_url=settings.ollama_base_url, qdrant_client=raw_client)
    retriever = HybridRetriever(qdrant=qdrant, embedding_pipeline=embedder)

    await embedder.index_chunks([_make_chunk(tenant_a_coverage_id, test_tenant_a_id)], test_tenant_a_id)
    await embedder.ensure_collection(test_tenant_b_id)

    # Sanity check: tenant A can find its own freshly indexed chunk.
    own_results = await retriever.retrieve(
        query="gross margin revenue", tenant_id=test_tenant_a_id, coverage_id=tenant_a_coverage_id
    )
    assert own_results, "setup failed -- tenant A couldn't retrieve its own indexed chunk"

    # Tenant B, given tenant A's coverage_id, must get nothing back.
    results = await retriever.retrieve(
        query="gross margin revenue", tenant_id=test_tenant_b_id, coverage_id=tenant_a_coverage_id
    )
    assert results == [], f"expected 0 results, got {len(results)} -- TENANT ISOLATION BREACH"


async def test_rls_direct_sql(db_session, tenant_b_coverage_id: str) -> None:
    """``db_session`` is scoped to tenant A (see tests/conftest.py). A row
    that genuinely belongs to tenant B (created via tenant B's own JWT, not a
    hardcoded id) must be invisible to a tenant-A-scoped session -- if the
    app's DB role has BYPASSRLS or owns the table without FORCE ROW LEVEL
    SECURITY, this is exactly the check that would catch it.
    """
    result = await db_session.execute(
        text("SELECT count(*) FROM coverages WHERE id = :cid"),
        {"cid": tenant_b_coverage_id},
    )
    count = result.scalar()
    assert count == 0, f"RLS failed: tenant-A session can see tenant-B's coverage row ({tenant_b_coverage_id})"
