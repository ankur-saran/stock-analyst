"""Tool functions callable by the Munger Invert agent.

``search_risk_factors`` and ``search_footnotes`` are section-filtered
retrievals -- unlike Lynch Pitch's general-purpose RAG queries, these force
the search into the specific parts of a filing where adversarial evidence
concentrates (risk factors, footnote disclosures) rather than trusting
semantic similarity alone to surface them. ``compare_narrative_to_data`` is
best-effort, same as Lynch Pitch's ``get_management_credibility_score``: it
degrades to ``None`` when there isn't enough history to compare, and callers
must treat it as optional context. ``save_bear_case`` always runs regardless
of citation coverage -- the Citation Enforcer, not this function, is
responsible for gating.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

import structlog
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.models import KpiTimeseries, OutputTypeEnum, ResearchOutput
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

_RISK_FACTORS_QUERY = "risk factors material risks litigation regulatory"
_FOOTNOTES_QUERY = "footnotes contingent liabilities off-balance-sheet operating leases"

_POSITIVE_NARRATIVE_RE = re.compile(
    r"\b(?:grow(?:th|ing)?|increas(?:e|ed|ing)|expand(?:ed|ing)?|"
    r"record|strong|improv(?:e|ed|ing)|accelerat(?:e|ed|ing))\b",
    re.IGNORECASE,
)


async def search_risk_factors(
    coverage_id: str, tenant_id: str, retriever: HybridRetriever
) -> list[dict[str, Any]]:
    """Search restricted to the filing's risk-factors section."""
    results = await retriever.retrieve(
        _RISK_FACTORS_QUERY,
        tenant_id,
        coverage_id,
        top_k=8,
        rerank_top_n=5,
        filters={"must": [{"key": "section_name", "match": {"any": ["risk_factors", "risk factors"]}}]},
    )
    return [
        {"chunk_id": r.chunk_id, "content": r.content, "metadata": r.metadata, "score": r.score}
        for r in results
    ]


async def search_footnotes(
    coverage_id: str, tenant_id: str, retriever: HybridRetriever
) -> list[dict[str, Any]]:
    """Search restricted to the filing's footnote/notes-to-financials section."""
    results = await retriever.retrieve(
        _FOOTNOTES_QUERY,
        tenant_id,
        coverage_id,
        top_k=8,
        rerank_top_n=5,
        filters={"must": [{"key": "section_name", "match": {"any": ["notes", "footnotes"]}}]},
    )
    return [
        {"chunk_id": r.chunk_id, "content": r.content, "metadata": r.metadata, "score": r.score}
        for r in results
    ]


async def compare_narrative_to_data(
    coverage_id: str, kpi_name: str, db: AsyncSession
) -> dict[str, Any] | None:
    """Flag divergence between management's narrative and the KPI's actual trend.

    Best-effort like Lynch Pitch's ``get_management_credibility_score`` --
    returns ``None`` when there isn't enough history (no KPI series or no
    prior quarterly update) to compare against, rather than guessing.
    """
    kpi_result = await db.execute(
        select(KpiTimeseries)
        .where(
            KpiTimeseries.coverage_id == uuid.UUID(coverage_id),
            KpiTimeseries.kpi_name == kpi_name,
        )
        .order_by(KpiTimeseries.extracted_at.desc())
        .limit(6)
    )
    rows = list(kpi_result.scalars().all())
    if not rows:
        return None
    actual_trend = [
        {"period": row.period, "value": row.value} for row in reversed(rows)
    ]

    update_result = await db.execute(
        select(ResearchOutput)
        .where(
            ResearchOutput.coverage_id == uuid.UUID(coverage_id),
            ResearchOutput.output_type == OutputTypeEnum.quarterly_update,
        )
        .order_by(ResearchOutput.generated_at.desc())
    )
    updates = update_result.scalars().all()
    if not updates:
        return None

    kpi_label = kpi_name.replace("_", " ")
    management_claim = next(
        (
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", updates[0].content)
            if kpi_label.lower() in sentence.lower()
        ),
        f"No prior guidance found for {kpi_label}",
    )

    divergence_detected = bool(
        _POSITIVE_NARRATIVE_RE.search(management_claim)
        and len(actual_trend) >= 2
        and actual_trend[-1]["value"] < actual_trend[0]["value"]
    )

    return {
        "management_claim": management_claim,
        "actual_trend": actual_trend,
        "divergence_detected": divergence_detected,
    }


async def save_bear_case(
    coverage_id: str,
    tenant_id: str,
    content: str,
    citations: list[dict[str, Any]],
    citation_coverage_pct: float,
    llm_used: str,
    tokens_used: int,
    db: AsyncSession,
) -> str:
    """INSERT into research_outputs with output_type="munger_invert"; return the output_id."""
    output = ResearchOutput(
        coverage_id=uuid.UUID(coverage_id),
        tenant_id=uuid.UUID(tenant_id),
        output_type=OutputTypeEnum.munger_invert,
        content=content,
        citations=citations,
        citation_coverage_pct=citation_coverage_pct,
        llm_used=llm_used,
        tokens_used=tokens_used,
    )
    db.add(output)
    await db.commit()
    await db.refresh(output)

    logger.info(
        "munger_invert.bear_case_saved",
        coverage_id=coverage_id,
        output_id=str(output.id),
        citation_coverage_pct=citation_coverage_pct,
    )
    return str(output.id)
