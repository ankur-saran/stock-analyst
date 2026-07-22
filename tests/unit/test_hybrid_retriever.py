"""Unit tests for HybridRetriever — no live Qdrant/Ollama/CrossEncoder required.

HybridRetriever is the security-critical component that must never search
without a tenant_id + coverage_id filter, so these tests focus on: the
mandatory-filter guard, that the filter is applied identically to both
searches, RRF fusion/dedup math, and parent hydration — all pure logic that
doesn't need real infrastructure. The CrossEncoder reranker is monkeypatched
out since loading it requires a model download.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

from rag.retrieval.hybrid_retriever import HybridRetriever
from rag.retrieval.reranker import Reranker

TENANT_ID = "tenant-a"
COVERAGE_ID = "coverage-123"


@dataclass
class _FakePoint:
    id: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


def _child_payload(chunk_id: str, parent_id: str | None = None) -> dict[str, Any]:
    return {
        "content": f"content for {chunk_id}",
        "chunk_type": "child",
        "tenant_id": TENANT_ID,
        "coverage_id": COVERAGE_ID,
        "parent_chunk_id": parent_id,
    }


@pytest.fixture()
def mock_qdrant() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def mock_embedder() -> AsyncMock:
    embedder = AsyncMock()
    embedder.collection_name = lambda tenant_id: f"tenant_{tenant_id}"  # sync method, not awaited
    embedder.embed_single.return_value = [0.1, 0.2, 0.3]
    embedder.compute_bm25_sparse.return_value = {1: 0.5}
    return embedder


@pytest.fixture()
def retriever(mock_qdrant: AsyncMock, mock_embedder: AsyncMock) -> HybridRetriever:
    return HybridRetriever(qdrant=mock_qdrant, embedding_pipeline=mock_embedder)


@pytest.fixture(autouse=True)
def stub_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Skip real CrossEncoder loading — rerank by keeping input order, tagging a score."""

    def _fake_rerank(self, query, chunks, top_n, model_name=None):
        return [{**c, "rerank_score": 1.0 - i * 0.01} for i, c in enumerate(chunks[:top_n])]

    monkeypatch.setattr(Reranker, "rerank", _fake_rerank)


# ── Mandatory tenant/coverage scoping ───────────────────────────────────────


async def test_retrieve_raises_without_tenant_id(retriever: HybridRetriever, mock_qdrant: AsyncMock):
    with pytest.raises(ValueError):
        await retriever.retrieve("query", "", COVERAGE_ID)
    mock_qdrant.search_dense.assert_not_called()
    mock_qdrant.search_sparse.assert_not_called()


async def test_retrieve_raises_without_coverage_id(retriever: HybridRetriever, mock_qdrant: AsyncMock):
    with pytest.raises(ValueError):
        await retriever.retrieve("query", TENANT_ID, "")
    mock_qdrant.search_dense.assert_not_called()
    mock_qdrant.search_sparse.assert_not_called()


async def test_retrieve_exact_quote_raises_without_tenant_scope(retriever: HybridRetriever):
    with pytest.raises(ValueError):
        await retriever.retrieve_exact_quote("some quote", None, COVERAGE_ID)  # type: ignore[arg-type]


async def test_retrieve_applies_identical_filter_to_dense_and_sparse(
    retriever: HybridRetriever, mock_qdrant: AsyncMock
):
    mock_qdrant.search_dense.return_value = []
    mock_qdrant.search_sparse.return_value = []

    await retriever.retrieve("query", TENANT_ID, COVERAGE_ID)

    dense_filter = mock_qdrant.search_dense.call_args.kwargs["filter_"]
    sparse_filter = mock_qdrant.search_sparse.call_args.kwargs["filter_"]
    assert dense_filter == sparse_filter

    keys = {clause["key"] for clause in dense_filter["must"]}
    assert {"tenant_id", "coverage_id", "chunk_type"} <= keys

    tenant_clause = next(c for c in dense_filter["must"] if c["key"] == "tenant_id")
    coverage_clause = next(c for c in dense_filter["must"] if c["key"] == "coverage_id")
    assert tenant_clause["match"]["value"] == TENANT_ID
    assert coverage_clause["match"]["value"] == COVERAGE_ID


async def test_retrieve_extra_filters_are_merged_not_replaced(
    retriever: HybridRetriever, mock_qdrant: AsyncMock
):
    mock_qdrant.search_dense.return_value = []
    mock_qdrant.search_sparse.return_value = []

    await retriever.retrieve(
        "query",
        TENANT_ID,
        COVERAGE_ID,
        filters={"must": [{"key": "filing_type", "match": {"value": "10-K"}}]},
    )

    dense_filter = mock_qdrant.search_dense.call_args.kwargs["filter_"]
    keys = {clause["key"] for clause in dense_filter["must"]}
    assert {"tenant_id", "coverage_id", "chunk_type", "filing_type"} <= keys


# ── RRF fusion ───────────────────────────────────────────────────────────────


async def test_rrf_fusion_dedups_and_sums_scores_across_lists(retriever: HybridRetriever):
    dense = [_FakePoint("a", 0.9, _child_payload("a")), _FakePoint("b", 0.8, _child_payload("b"))]
    sparse = [_FakePoint("b", 5.0, _child_payload("b")), _FakePoint("c", 4.0, _child_payload("c"))]

    fused = retriever._reciprocal_rank_fusion(dense, sparse, k=60)
    ids = [f["chunk_id"] for f in fused]

    # "b" appears rank 2 in dense and rank 1 in sparse -> highest combined score
    assert ids[0] == "b"
    assert set(ids) == {"a", "b", "c"}
    assert len(ids) == len(set(ids))  # no duplicate entries


async def test_rrf_fusion_of_empty_lists_is_empty(retriever: HybridRetriever):
    assert retriever._reciprocal_rank_fusion([], []) == []


# ── Parent hydration ─────────────────────────────────────────────────────────


async def test_hydrate_parents_attaches_parent_content(
    retriever: HybridRetriever, mock_qdrant: AsyncMock
):
    parent_point = _FakePoint("parent-1", 0.0, {"content": "full parent section text"})
    mock_qdrant.get_point.return_value = parent_point

    candidates = [
        {
            "chunk_id": "child-1",
            "content": "child text",
            "metadata": _child_payload("child-1", parent_id="parent-1"),
            "rrf_score": 0.5,
        }
    ]

    hydrated = await retriever._hydrate_parents(candidates, TENANT_ID)

    assert len(hydrated) == 1
    assert hydrated[0].parent_chunk_id == "parent-1"
    assert hydrated[0].parent_content == "full parent section text"
    mock_qdrant.get_point.assert_awaited_once_with(f"tenant_{TENANT_ID}", "parent-1")


async def test_hydrate_parents_leaves_parent_content_none_without_parent(
    retriever: HybridRetriever, mock_qdrant: AsyncMock
):
    candidates = [
        {
            "chunk_id": "child-1",
            "content": "child text",
            "metadata": _child_payload("child-1", parent_id=None),
            "rrf_score": 0.5,
        }
    ]

    hydrated = await retriever._hydrate_parents(candidates, TENANT_ID)

    assert hydrated[0].parent_content is None
    mock_qdrant.get_point.assert_not_called()


# ── retrieve_exact_quote ─────────────────────────────────────────────────────


async def test_retrieve_exact_quote_returns_none_below_threshold(
    retriever: HybridRetriever, mock_qdrant: AsyncMock
):
    mock_qdrant.search_sparse.return_value = [_FakePoint("x", 0.1, _child_payload("x"))]
    result = await retriever.retrieve_exact_quote("some quote", TENANT_ID, COVERAGE_ID)
    assert result is None


async def test_retrieve_exact_quote_returns_chunk_above_threshold(
    retriever: HybridRetriever, mock_qdrant: AsyncMock
):
    mock_qdrant.search_sparse.return_value = [_FakePoint("x", 0.9, _child_payload("x"))]
    result = await retriever.retrieve_exact_quote("some quote", TENANT_ID, COVERAGE_ID)
    assert result is not None
    assert result.chunk_id == "x"
    assert result.score == 0.9


async def test_retrieve_exact_quote_returns_none_when_no_hits(
    retriever: HybridRetriever, mock_qdrant: AsyncMock
):
    mock_qdrant.search_sparse.return_value = []
    result = await retriever.retrieve_exact_quote("some quote", TENANT_ID, COVERAGE_ID)
    assert result is None
