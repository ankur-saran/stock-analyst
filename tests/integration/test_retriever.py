"""
Integration tests for HybridRetriever.

Prerequisites:
  - Qdrant running and reachable at settings.qdrant_host:settings.qdrant_port
  - Ollama running at settings.ollama_base_url with `nomic-embed-text:v1.5` pulled
  - `sentence-transformers` able to download `cross-encoder/ms-marco-MiniLM-L-6-v2`
    on first use (or a warm HF cache)

The module fixture indexes a short synthetic "AAPL 10-K MD&A" passage into
tenant A's collection only — this stands in for "AAPL 10-K already indexed"
without depending on a real filing or the full ingestion pipeline. Tenant B's
collection is created but left empty, so cross-tenant queries exercise a real
(zero-hit) search rather than a missing-collection error.

Run:
    pytest tests/integration/test_retriever.py -v
"""
from __future__ import annotations

import time
import uuid

import pytest
import pytest_asyncio
from qdrant_client import QdrantClient

from rag.connectors.qdrant_client import QdrantConnector
from rag.ingestion.chunkers.hierarchical import Chunk
from rag.ingestion.pipeline import EmbeddingPipeline
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.config import Settings

settings = Settings()

TENANT_A_ID = str(uuid.uuid4())
TENANT_B_ID = str(uuid.uuid4())
COVERAGE_ID = str(uuid.uuid4())  # belongs to tenant A
DOCUMENT_ID = str(uuid.uuid4())

_MDA_PASSAGE = (
    "Gross margin expanded to 45.2% in fiscal 2023, up from 43.3% a year earlier, "
    "driven by a favorable product mix and lower commodity costs. "
    "Total net revenue increased 8% year over year to $394.3 billion, "
    "reflecting continued strength in Services and wearables. "
    "Operating expenses grew more slowly than revenue, expanding operating margin. "
    "Management expects gross margin to remain in a similar range next quarter."
)


def _make_child_chunk(content: str, index: int) -> Chunk:
    metadata = {
        "document_id": DOCUMENT_ID,
        "document_name": "AAPL_10K_2023.pdf",
        "filing_type": "10-K",
        "period": "FY2023",
        "section_name": "mda",
        "tenant_id": TENANT_A_ID,
        "coverage_id": COVERAGE_ID,
        "page_number": 30,
        "chunk_type": "child",
        "parent_chunk_id": None,
        "char_start": index * 200,
        "char_end": index * 200 + len(content),
        "token_estimate": len(content.split()),
    }
    return Chunk(
        chunk_id=str(uuid.uuid4()),
        content=content,
        chunk_type="child",
        parent_chunk_id=None,
        metadata=metadata,
    )


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def embedding_pipeline() -> EmbeddingPipeline:
    client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    return EmbeddingPipeline(ollama_url=settings.ollama_base_url, qdrant_client=client)


@pytest_asyncio.fixture(scope="module")
async def qdrant_connector() -> QdrantConnector:
    return QdrantConnector(host=settings.qdrant_host, port=settings.qdrant_port)


@pytest_asyncio.fixture(scope="module", autouse=True)
async def indexed_aapl_filing(embedding_pipeline: EmbeddingPipeline):
    """Index a synthetic AAPL 10-K MD&A passage for tenant A; leave tenant B empty."""
    sentences = [s.strip() + "." for s in _MDA_PASSAGE.split(". ") if s.strip()]
    chunks = [_make_child_chunk(sentence, i) for i, sentence in enumerate(sentences)]

    await embedding_pipeline.index_chunks(chunks, TENANT_A_ID)
    await embedding_pipeline.ensure_collection(TENANT_B_ID)  # exists, but has no matching data
    yield


@pytest_asyncio.fixture()
async def retriever(
    qdrant_connector: QdrantConnector, embedding_pipeline: EmbeddingPipeline
) -> HybridRetriever:
    return HybridRetriever(qdrant=qdrant_connector, embedding_pipeline=embedding_pipeline)


# ── Test cases ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retrieve_returns_results_for_semantic_query(retriever: HybridRetriever):
    results = await retriever.retrieve(
        "gross margin trend", TENANT_A_ID, COVERAGE_ID, rerank_top_n=8
    )
    assert 0 < len(results) <= 8


@pytest.mark.asyncio
async def test_retrieve_only_returns_searchable_chunk_types(retriever: HybridRetriever):
    results = await retriever.retrieve("gross margin trend", TENANT_A_ID, COVERAGE_ID)
    assert results
    for chunk in results:
        assert chunk.metadata["chunk_type"] in ("child", "table")


@pytest.mark.asyncio
async def test_retrieve_only_returns_matching_tenant(retriever: HybridRetriever):
    results = await retriever.retrieve("gross margin trend", TENANT_A_ID, COVERAGE_ID)
    assert results
    for chunk in results:
        assert chunk.metadata["tenant_id"] == TENANT_A_ID


@pytest.mark.asyncio
async def test_retrieve_cross_tenant_returns_zero_results(retriever: HybridRetriever):
    """Coverage belongs to tenant A; tenant B must never see its chunks."""
    results = await retriever.retrieve("gross margin trend", TENANT_B_ID, COVERAGE_ID)
    assert results == []


@pytest.mark.asyncio
async def test_retrieve_exact_quote_finds_known_phrase(retriever: HybridRetriever):
    chunk = await retriever.retrieve_exact_quote(
        "revenue increased 8%", TENANT_A_ID, COVERAGE_ID
    )
    assert chunk is not None
    assert "revenue increased 8" in chunk.content.lower()


@pytest.mark.asyncio
async def test_retrieve_exact_quote_cross_tenant_returns_none(retriever: HybridRetriever):
    chunk = await retriever.retrieve_exact_quote(
        "revenue increased 8%", TENANT_B_ID, COVERAGE_ID
    )
    assert chunk is None


@pytest.mark.asyncio
async def test_retrieve_rejects_missing_tenant_or_coverage(retriever: HybridRetriever):
    with pytest.raises(ValueError):
        await retriever.retrieve("gross margin trend", "", COVERAGE_ID)
    with pytest.raises(ValueError):
        await retriever.retrieve("gross margin trend", TENANT_A_ID, "")


@pytest.mark.asyncio
async def test_retrieve_p95_latency_under_500ms(retriever: HybridRetriever):
    durations: list[float] = []
    for _ in range(10):
        start = time.perf_counter()
        await retriever.retrieve("gross margin trend", TENANT_A_ID, COVERAGE_ID)
        durations.append(time.perf_counter() - start)

    durations.sort()
    p95_ms = durations[min(len(durations) - 1, int(len(durations) * 0.95))] * 1000
    assert p95_ms < 500, f"p95 retrieval latency {p95_ms:.1f}ms exceeds the 500ms budget"
