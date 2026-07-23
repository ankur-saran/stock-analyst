"""Tool functions callable by the Industry Analyst agent.

``web_search`` and ``fetch_url`` are the two research primitives (Tavily and
a domain-allowlisted direct fetch, respectively); ``rag_search_industry``
lets the agent pull in anything a tenant has already uploaded about the
industry; ``save_industry_primer`` is the one write this agent ever performs
— a direct UPDATE of the shared, tenant-less ``industries`` row, since the
primer is reused platform-wide rather than scoped to a coverage.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import structlog
from bs4 import BeautifulSoup
from shared.config import Settings
from shared.models import Industry
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

settings = Settings()

_TAVILY_SEARCH_URL = "https://api.tavily.com/search"

# Regulator / industry-body domains only — this agent never fetches arbitrary
# URLs, so a compromised or hallucinated URL from the LLM can't be used to
# reach internal services (SSRF).
ALLOWED_DOMAINS = {
    "sec.gov",
    "bis.org",
    "imf.org",
    "worldbank.org",
    "oecd.org",
    "federalreserve.gov",
    "statista.com",
    "mckinsey.com",
    "bain.com",
    "deloitte.com",
    "pwc.com",
    "bcg.com",
}

_FETCH_TRUNCATE_CHARS = 5000
# Global collection industry-scoped documents are ingested into — distinct
# from the per-tenant `tenant_{tenant_id}` collections coverage research
# reads from, since industry primers are shared across every tenant.
_INDUSTRY_COLLECTION = "industry_documents"


async def web_search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """Call Tavily's search API and return normalized result dicts."""
    api_key = settings.tavily_api_key.get_secret_value()
    if not api_key or api_key == "tvly-...":
        raise ValueError("TAVILY_API_KEY is not configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _TAVILY_SEARCH_URL,
            json={
                "api_key": api_key,
                "query": query,
                "max_results": max_results,
                "search_depth": "advanced",
                "include_answer": False,
            },
        )
        response.raise_for_status()

    body = response.json()
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "published_date": r.get("published_date"),
            "content": r.get("content", ""),
        }
        for r in body.get("results", [])
    ]


async def fetch_url(url: str) -> str:
    """Fetch a regulator/industry-body URL and return its extracted text.

    Restricted to ``ALLOWED_DOMAINS`` to prevent SSRF — an LLM-supplied URL is
    untrusted input, and without this allowlist it could be pointed at
    internal services instead of the public sources it claims to cite.
    """
    domain = urlparse(url).netloc.lstrip("www.")
    if not any(domain == d or domain.endswith(f".{d}") for d in ALLOWED_DOMAINS):
        raise ValueError(f"Domain not in allowlist: {domain}")

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    return text[:_FETCH_TRUNCATE_CHARS]


async def rag_search_industry(
    query: str, industry_id: str, retriever: Any, top_k: int = 8
) -> list[dict[str, Any]]:
    """Search documents tagged to this industry, across every tenant.

    Unlike coverage research (tenant + coverage scoped via
    ``HybridRetriever.retrieve``), industry-body documents live in a single
    shared collection filtered on ``industry_id`` rather than
    ``tenant_id``/``coverage_id`` — there's no per-tenant isolation concern
    here because industry primers are, by design, shared across tenants.
    """
    if not industry_id:
        raise ValueError("industry_id is required")

    query_embedding = await retriever.embedder.embed_single(query)
    filter_ = {"must": [{"key": "industry_id", "match": {"value": industry_id}}]}
    results = await retriever.qdrant.search_dense(
        collection=_INDUSTRY_COLLECTION,
        query_vector=query_embedding,
        filter_=filter_,
        limit=top_k,
    )
    return [
        {
            "content": (r.payload or {}).get("content", ""),
            "metadata": r.payload or {},
            "score": r.score,
        }
        for r in results
    ]


async def save_industry_primer(
    industry_id: str,
    content: str,
    citations: list[dict[str, Any]],
    llm_used: str,
    db: AsyncSession,
) -> str:
    """Persist the generated primer onto the shared ``industries`` row."""
    industry = await db.get(Industry, uuid.UUID(industry_id))
    if industry is None:
        raise ValueError(f"Industry {industry_id} not found")

    industry.primer_content = content
    industry.primer_citations = citations
    industry.word_count = len(content.split())
    industry.llm_used = llm_used
    industry.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info("industry_analyst.primer_saved", industry_id=industry_id, word_count=industry.word_count)
    return industry_id
