"""Lazy-loaded CrossEncoder reranker.

Loading a CrossEncoder takes ~2s, so the model is cached as a class-level
singleton and loaded on first use rather than per-request — a Celery/API
worker process pays that cost once, at first query, not on every call.
"""
from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger()

DEFAULT_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"


class Reranker:
    _model: Any = None
    _model_name: str | None = None

    @classmethod
    def get_model(cls, model_name: str = DEFAULT_MODEL_NAME) -> Any:
        if cls._model is None or cls._model_name != model_name:
            from sentence_transformers import CrossEncoder

            logger.info("reranker.loading_model", model_name=model_name)
            cls._model = CrossEncoder(model_name)
            cls._model_name = model_name
        return cls._model

    def rerank(
        self,
        query: str,
        chunks: list[dict[str, Any]],
        top_n: int,
        model_name: str = DEFAULT_MODEL_NAME,
    ) -> list[dict[str, Any]]:
        """Score (query, chunk) pairs and return the top_n chunks, each tagged with rerank_score."""
        if not chunks:
            return []

        model = self.get_model(model_name)
        pairs = [(query, c["content"]) for c in chunks]
        scores = model.predict(pairs)

        scored = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
        return [{**chunk, "rerank_score": float(score)} for chunk, score in scored[:top_n]]
