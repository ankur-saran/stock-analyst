"""Ad-hoc RAG search over a coverage's indexed documents.

Backs the Analyst Notes editor's `@`-citation search popup: the analyst
types a query, this returns the top matches, and selecting one inserts a
`[Document, Section]: "quote"` citation. It's a thin wrapper around
``HybridRetriever.retrieve`` — the same retrieval path every research agent
uses — so a citation inserted from a search result is text that genuinely
exists in the tenant's indexed documents and will pass the Citation
Enforcer's exact-quote check if that note content is ever re-validated.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query

from agents.orchestrator.graph import get_retriever

from apps.api.db import DbSession
from apps.api.middleware.auth import CurrentUser, get_current_user
from apps.api.routers.outputs import _get_owned_coverage

router = APIRouter(prefix="/coverages", tags=["search"])

_TOP_K = 5
# Quotes must stay short enough to be a usable inline citation, and slicing
# a hydrated chunk's text still yields a literal substring of indexed
# content -- it just may end mid-sentence.
_MAX_QUOTE_CHARS = 400


@router.get("/{coverage_id}/search")
async def search_coverage(
    coverage_id: str,
    db: DbSession,
    current_user: CurrentUser = Depends(get_current_user),
    q: str = Query(..., min_length=1),
) -> list[dict[str, Any]]:
    coverage = await _get_owned_coverage(db, coverage_id, current_user.tenant_id)

    retriever = get_retriever()
    results = await retriever.retrieve(
        query=q,
        tenant_id=str(current_user.tenant_id),
        coverage_id=str(coverage.id),
        rerank_top_n=_TOP_K,
    )

    return [
        {
            "chunk_id": r.chunk_id,
            "document_name": r.metadata.get("document_name", "Unknown Document"),
            "section": r.metadata.get("section_name", "Unknown Section"),
            "quote": (r.content or "").strip()[:_MAX_QUOTE_CHARS],
            "score": r.score,
        }
        for r in results[:_TOP_K]
    ]
