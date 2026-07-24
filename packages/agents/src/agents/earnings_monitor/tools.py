"""Tool functions callable by the Earnings Monitor agent.

``compare_management_language`` looks for recurring excuse phrases across
this coverage's history, excluding the current filing, without needing a
document list up front -- it retrieves broadly then filters out the current
document's chunks by ``document_id``, which is all the tool's signature
(``coverage_id``, ``current_doc_id``, ``tenant_id``, ``retriever`` -- no db
session) allows. ``update_credibility_score`` accumulates a per-quarter
verdict on the most recently saved quarterly update's
``output_metadata`` JSONB column so it can be read back to build a
management track record over time. ``save_quarterly_update`` mirrors Lynch
Pitch's ``save_bull_case``/Munger Invert's ``save_bear_case`` but, unlike
those two, is passed the Citation Enforcer's actual verdict -- Earnings
Monitor validates before saving rather than leaving that to a separate graph
node. ``trigger_kpi_tracker`` hands off to the same Celery dispatch path the
Orchestrator uses.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

import structlog
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.models import OutputTypeEnum, ResearchOutput
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator.tools import dispatch_task

logger = structlog.get_logger()

_EXCUSE_PHRASES = ("supply chain", "macro environment", "temporary", "one-time", "headwind")


async def compare_management_language(
    coverage_id: str, current_doc_id: str, tenant_id: str, retriever: HybridRetriever
) -> str:
    """Frequency of recurring management excuse phrases across historical filings."""
    lines = ["RECURRING MANAGEMENT LANGUAGE (excuse-phrase frequency across historical filings):"]

    for phrase in _EXCUSE_PHRASES:
        results = await retriever.retrieve(phrase, tenant_id, coverage_id, top_k=15, rerank_top_n=10)
        historical = [r for r in results if r.metadata.get("document_id") != current_doc_id]
        if not historical:
            continue
        periods = sorted({r.metadata.get("period", "Unknown") for r in historical})
        lines.append(f'- "{phrase}": used {len(historical)} time(s) across [{", ".join(periods)}]')

    if len(lines) == 1:
        return "RECURRING MANAGEMENT LANGUAGE: none of the tracked excuse phrases recur across historical filings."
    return "\n".join(lines)


async def update_credibility_score(coverage_id: str, quarter: str, score: str, db: AsyncSession) -> None:
    """Accumulate this quarter's credibility verdict on the latest quarterly_update row."""
    result = await db.execute(
        select(ResearchOutput)
        .where(
            ResearchOutput.coverage_id == uuid.UUID(coverage_id),
            ResearchOutput.output_type == OutputTypeEnum.quarterly_update,
        )
        .order_by(ResearchOutput.generated_at.desc())
    )
    latest = result.scalars().first()
    if latest is None:
        logger.warning("earnings_monitor.no_quarterly_update_to_score", coverage_id=coverage_id)
        return

    history = dict(latest.output_metadata or {})
    history[quarter] = {
        "credibility_score": score,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    latest.output_metadata = history
    await db.commit()


async def save_quarterly_update(
    coverage_id: str,
    tenant_id: str,
    content: str,
    citations: list[dict[str, Any]],
    citation_coverage_pct: float,
    approved_by_enforcer: bool,
    enforcer_status: str,
    llm_used: str,
    tokens_used: int,
    db: AsyncSession,
) -> str:
    """INSERT into research_outputs with output_type="quarterly_update"; return the output_id."""
    output = ResearchOutput(
        coverage_id=uuid.UUID(coverage_id),
        tenant_id=uuid.UUID(tenant_id),
        output_type=OutputTypeEnum.quarterly_update,
        content=content,
        citations=citations,
        citation_coverage_pct=citation_coverage_pct,
        approved_by_enforcer=approved_by_enforcer,
        enforcer_status=enforcer_status,
        llm_used=llm_used,
        tokens_used=tokens_used,
    )
    db.add(output)
    await db.commit()
    await db.refresh(output)

    logger.info(
        "earnings_monitor.quarterly_update_saved",
        coverage_id=coverage_id,
        output_id=str(output.id),
        citation_coverage_pct=citation_coverage_pct,
        enforcer_status=enforcer_status,
    )
    return str(output.id)


async def trigger_kpi_tracker(
    coverage_id: str, tenant_id: str, new_document_id: str, db: AsyncSession
) -> str:
    """Dispatch a KPI Tracker run for the newly-approved filing."""
    return await dispatch_task(
        agent="kpi_tracker",
        skill="extract",
        payload={"new_document_id": new_document_id},
        coverage_id=coverage_id,
        tenant_id=tenant_id,
        db=db,
    )
