"""Two-stage hybrid retrieval: dense + sparse -> RRF fusion -> reranking -> parent hydration.

This is the most security-critical component in the retrieval layer. Every
Qdrant collection is per-tenant (``tenant_{tenant_id}``, see
:class:`~rag.ingestion.pipeline.EmbeddingPipeline`), but a collection can
still hold chunks from many coverages, so ``retrieve`` additionally filters
on ``coverage_id`` — and that filter is applied identically to both the
dense and sparse search calls. ``retrieve`` and ``retrieve_exact_quote``
raise ``ValueError`` immediately if either identifier is missing rather than
silently searching without them.

BM25 (sparse) finds the exact phrase a citation claims to quote; dense
search finds the semantic neighborhood around it; the CrossEncoder reranker
picks the passages actually relevant to the query; parent hydration then
attaches the full section text so the LLM has broader context than the
~200-token child chunk alone.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import structlog
from qdrant_client import models

from rag.connectors.qdrant_client import QdrantConnector
from rag.ingestion.pipeline import EmbeddingPipeline
from rag.retrieval.reranker import DEFAULT_MODEL_NAME, Reranker

logger = structlog.get_logger()

_SEARCHABLE_CHUNK_TYPES = ("child", "table")
_RRF_K = 60
_EXACT_QUOTE_SCORE_THRESHOLD = 0.5


@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    metadata: dict[str, Any]
    score: float
    parent_content: str | None
    parent_chunk_id: str | None


class HybridRetriever:
    def __init__(
        self,
        qdrant: QdrantConnector,
        embedding_pipeline: EmbeddingPipeline,
        reranker_model: str = DEFAULT_MODEL_NAME,
    ) -> None:
        self.qdrant = qdrant
        self.embedder = embedding_pipeline
        self.reranker_model = reranker_model
        self.reranker = Reranker()

    # ── Public API ────────────────────────────────────────────────────────────

    async def retrieve(
        self,
        query: str,
        tenant_id: str,
        coverage_id: str,
        top_k: int = 20,
        rerank_top_n: int = 8,
        filters: dict[str, Any] | None = None,
    ) -> list[RetrievedChunk]:
        self._require_tenant_scope(tenant_id, coverage_id)
        collection = self.embedder.collection_name(tenant_id)
        base_filter = self._build_filter(tenant_id, coverage_id, filters)

        query_embedding = await self.embedder.embed_single(query)
        dense_results = await self.qdrant.search_dense(
            collection=collection,
            query_vector=query_embedding,
            filter_=base_filter,
            limit=top_k,
        )

        sparse_vec = self.embedder.compute_bm25_sparse(query)
        sparse_results = await self.qdrant.search_sparse(
            collection=collection,
            sparse_vector=sparse_vec,
            filter_=base_filter,
            limit=top_k,
        )

        candidates = self._reciprocal_rank_fusion(dense_results, sparse_results)
        reranked = await asyncio.to_thread(self._rerank, query, candidates, rerank_top_n)
        hydrated = await self._hydrate_parents(reranked, tenant_id)

        logger.info(
            "hybrid_retriever.retrieve",
            tenant_id=tenant_id,
            coverage_id=coverage_id,
            dense_hits=len(dense_results),
            sparse_hits=len(sparse_results),
            candidates=len(candidates),
            returned=len(hydrated),
        )
        return hydrated

    async def retrieve_exact_quote(
        self, quote: str, tenant_id: str, coverage_id: str
    ) -> RetrievedChunk | None:
        """BM25-only lookup for a claimed quote — used by the Citation Enforcer."""
        self._require_tenant_scope(tenant_id, coverage_id)
        collection = self.embedder.collection_name(tenant_id)
        base_filter = self._build_filter(tenant_id, coverage_id, None)

        sparse_vec = self.embedder.compute_bm25_sparse(quote)
        if not sparse_vec:
            return None

        results = await self.qdrant.search_sparse(
            collection=collection,
            sparse_vector=sparse_vec,
            filter_=base_filter,
            limit=1,
        )
        if not results:
            return None

        top = results[0]
        if top.score is None or top.score < _EXACT_QUOTE_SCORE_THRESHOLD:
            return None

        payload = top.payload or {}
        return RetrievedChunk(
            chunk_id=str(top.id),
            content=payload.get("content", ""),
            metadata=payload,
            score=top.score,
            parent_content=None,
            parent_chunk_id=payload.get("parent_chunk_id"),
        )

    # ── Stage helpers ─────────────────────────────────────────────────────────

    @staticmethod
    def _require_tenant_scope(tenant_id: str, coverage_id: str) -> None:
        if not tenant_id or not coverage_id:
            raise ValueError(
                "tenant_id and coverage_id are mandatory — retrieval must never run "
                "without both filters"
            )

    @staticmethod
    def _build_filter(
        tenant_id: str, coverage_id: str, filters: dict[str, Any] | None
    ) -> dict[str, Any]:
        must: list[dict[str, Any]] = [
            {"key": "tenant_id", "match": {"value": tenant_id}},
            {"key": "coverage_id", "match": {"value": coverage_id}},
            {"key": "chunk_type", "match": {"any": list(_SEARCHABLE_CHUNK_TYPES)}},
        ]
        if filters:
            must.extend(filters.get("must", []))
        return {"must": must}

    def _reciprocal_rank_fusion(
        self,
        dense: list[models.ScoredPoint],
        sparse: list[models.ScoredPoint],
        k: int = _RRF_K,
    ) -> list[dict[str, Any]]:
        scores: dict[str, float] = {}
        payloads: dict[str, dict[str, Any]] = {}

        for result_list in (dense, sparse):
            for rank, point in enumerate(result_list, start=1):
                chunk_id = str(point.id)
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (k + rank)
                payloads.setdefault(chunk_id, point.payload or {})

        ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)
        return [
            {
                "chunk_id": chunk_id,
                "content": payloads[chunk_id].get("content", ""),
                "metadata": payloads[chunk_id],
                "rrf_score": scores[chunk_id],
            }
            for chunk_id in ranked_ids
        ]

    def _rerank(
        self, query: str, candidates: list[dict[str, Any]], top_n: int
    ) -> list[dict[str, Any]]:
        return self.reranker.rerank(query, candidates, top_n, model_name=self.reranker_model)

    async def _hydrate_parents(
        self, chunks: list[dict[str, Any]], tenant_id: str
    ) -> list[RetrievedChunk]:
        collection = self.embedder.collection_name(tenant_id)
        hydrated: list[RetrievedChunk] = []

        for chunk in chunks:
            metadata = chunk["metadata"]
            parent_chunk_id = metadata.get("parent_chunk_id")
            parent_content: str | None = None

            if parent_chunk_id:
                parent_record = await self.qdrant.get_point(collection, parent_chunk_id)
                if parent_record is not None and parent_record.payload:
                    parent_content = parent_record.payload.get("content")

            hydrated.append(
                RetrievedChunk(
                    chunk_id=chunk["chunk_id"],
                    content=chunk["content"],
                    metadata=metadata,
                    score=chunk.get("rerank_score", chunk.get("rrf_score", 0.0)),
                    parent_content=parent_content,
                    parent_chunk_id=parent_chunk_id,
                )
            )

        return hydrated
