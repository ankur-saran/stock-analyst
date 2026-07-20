"""Embeds chunks via Ollama and indexes them into a per-tenant Qdrant hybrid collection.

Every collection is named ``{collection_prefix}_{tenant_id}`` — there is no
shared collection across tenants, so a filter bug can never leak another
tenant's chunks. Dense vectors give semantic recall; sparse BM25-style
vectors give the exact-term matching the Citation Enforcer needs to verify a
quote actually appears in the source filing. Parent chunks are stored
payload-only (no vectors) purely for hydration once a child chunk is
retrieved — they must never be searchable directly.
"""
from __future__ import annotations

import asyncio
import re
from collections import Counter
from zlib import crc32

import httpx
import structlog
from qdrant_client import QdrantClient, models
from rank_bm25 import BM25Okapi

from rag.ingestion.chunkers.hierarchical import Chunk

logger = structlog.get_logger()

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_BM25_VOCAB_SIZE = 30000
_UPSERT_BATCH_SIZE = 100
_SEARCHABLE_CHUNK_TYPES = ("child", "table")

_STOPWORDS = frozenset(
    """
    a an the and or but if while of at by for with about against between into
    through during before after above below to from up down in out on off
    over under again further then once here there all any both each few more
    most other some such no nor not only own same so than too very s t can
    will just don should now is are was were be been being have has had do
    does did doing this that these those i you he she it we they what which
    who whom as
    """.split()
)


def _tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


class EmbeddingPipeline:
    def __init__(
        self,
        ollama_url: str,
        qdrant_client: QdrantClient,
        collection_prefix: str = "tenant",
        http_client: httpx.Client | None = None,
    ) -> None:
        self.ollama_url = ollama_url.rstrip("/")
        self.qdrant = qdrant_client
        self.collection_prefix = collection_prefix
        self.model_name = "nomic-embed-text:v1.5"
        self.vector_dim = 768
        self.batch_size = 32
        self._http = http_client or httpx.Client(timeout=30.0)

    def collection_name(self, tenant_id: str) -> str:
        return f"{self.collection_prefix}_{tenant_id}"

    # ── Collection setup ──────────────────────────────────────────────────────

    async def ensure_collection(self, tenant_id: str) -> None:
        await asyncio.to_thread(self._ensure_collection_sync, tenant_id)

    def _ensure_collection_sync(self, tenant_id: str) -> None:
        name = self.collection_name(tenant_id)
        existing = {c.name for c in self.qdrant.get_collections().collections}
        if name in existing:
            return
        self.qdrant.create_collection(
            collection_name=name,
            vectors_config={
                "dense": models.VectorParams(size=self.vector_dim, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={"sparse": models.SparseVectorParams()},
        )

    # ── Dense embeddings via Ollama ──────────────────────────────────────────

    async def embed_single(self, text: str) -> list[float]:
        return await asyncio.to_thread(self._embed_one_sync, text)

    def _embed_one_sync(self, text: str) -> list[float]:
        response = self._http.post(
            f"{self.ollama_url}/api/embeddings",
            json={"model": self.model_name, "prompt": text},
        )
        response.raise_for_status()
        return response.json()["embedding"]

    async def embed_chunks(self, chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]:
        results: list[tuple[Chunk, list[float]]] = []
        for i in range(0, len(chunks), self.batch_size):
            batch = chunks[i : i + self.batch_size]
            embeddings = await asyncio.gather(*(self.embed_single(c.content) for c in batch))
            results.extend(zip(batch, embeddings))
        return results

    # ── Sparse BM25 vectors ───────────────────────────────────────────────────

    def compute_bm25_sparse(self, text: str) -> dict[int, float]:
        tokens = _tokenize(text)
        if not tokens:
            return {}

        # BM25Okapi's idf is corpus-wide; there's no persistent corpus to
        # score a chunk against here, and with a corpus-of-one every term has
        # document frequency 1 of 1, which makes idf negative (and therefore
        # useless as a weight) for every token. So we use only BM25's
        # term-frequency saturation component — how much a repeated term's
        # contribution flattens out — via the library's k1/b constants.
        bm25 = BM25Okapi([tokens])
        doc_len = bm25.doc_len[0]
        freqs = Counter(tokens)

        weights: dict[int, float] = {}
        for token, freq in freqs.items():
            tf_component = (freq * (bm25.k1 + 1)) / (
                freq + bm25.k1 * (1 - bm25.b + bm25.b * doc_len / bm25.avgdl)
            )
            # Python's builtin hash() is randomized per-process for str, which
            # would make a token's vector index differ between the process
            # that indexed it and the process that later queries it — use a
            # stable hash instead.
            token_id = crc32(token.encode("utf-8")) % _BM25_VOCAB_SIZE
            weights[token_id] = weights.get(token_id, 0.0) + tf_component
        return weights

    # ── Indexing ──────────────────────────────────────────────────────────────

    async def index_chunks(self, chunks: list[Chunk], tenant_id: str) -> int:
        await self.ensure_collection(tenant_id)
        collection = self.collection_name(tenant_id)

        searchable = [c for c in chunks if c.chunk_type in _SEARCHABLE_CHUNK_TYPES]
        parents = [c for c in chunks if c.chunk_type not in _SEARCHABLE_CHUNK_TYPES]

        points: list[models.PointStruct] = []

        for chunk, dense_vector in await self.embed_chunks(searchable):
            sparse = self.compute_bm25_sparse(chunk.content)
            points.append(
                models.PointStruct(
                    id=chunk.chunk_id,
                    vector={
                        "dense": dense_vector,
                        "sparse": models.SparseVector(
                            indices=list(sparse.keys()), values=list(sparse.values())
                        ),
                    },
                    payload={**chunk.metadata, "content": chunk.content},
                )
            )

        for chunk in parents:
            points.append(
                models.PointStruct(
                    id=chunk.chunk_id,
                    vector={},
                    payload={**chunk.metadata, "content": chunk.content},
                )
            )

        for i in range(0, len(points), _UPSERT_BATCH_SIZE):
            batch = points[i : i + _UPSERT_BATCH_SIZE]
            await asyncio.to_thread(self.qdrant.upsert, collection_name=collection, points=batch)

        logger.info(
            "pipeline.indexed_chunks",
            tenant_id=tenant_id,
            collection=collection,
            total_points=len(points),
            searchable=len(searchable),
            parents=len(parents),
        )
        return len(points)
