"""Tool functions callable by the Lynch Pitch agent.

``get_financial_summary`` pre-populates verified numbers (with their
original citation) from ``kpi_timeseries`` before the LLM starts its RAG
search, so it has something to check its own extracted figures against
rather than re-deriving them from prose. ``get_management_credibility_score``
is best-effort: the Earnings Monitor agent that would populate a structured
``quarterly_update`` field doesn't exist yet, so this parses a
"Management credibility: Strong/Mixed/Weak" phrase out of prior quarterly
prose and degrades to ``None`` if it isn't there -- callers must treat it as
optional context, never a required input. ``save_bull_case`` is the one
write this agent performs before the Citation Enforcer has had a chance to
approve or reject the output; it always runs, regardless of coverage, since
the Enforcer (not this function) is responsible for gating.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

import structlog
from shared.models import KpiTimeseries, OutputTypeEnum, ResearchOutput
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# The standard KPI names the pitch cross-checks against -- matches the
# vocabulary KPI Tracker is expected to write into kpi_timeseries.kpi_name.
_STANDARD_KPI_NAMES = (
    "revenue",
    "gross_margin",
    "operating_margin",
    "fcf",
    "net_debt",
    "cash_and_equivalents",
    "total_debt",
)

_MANAGEMENT_CREDIBILITY_RE = re.compile(
    r"management\s+credibility[:\s]+(strong|mixed|weak)", re.IGNORECASE
)


async def get_financial_summary(coverage_id: str, db: AsyncSession) -> dict[str, dict[str, Any]]:
    """Latest known value of each standard KPI for this coverage."""
    result = await db.execute(
        select(KpiTimeseries)
        .where(
            KpiTimeseries.coverage_id == uuid.UUID(coverage_id),
            KpiTimeseries.kpi_name.in_(_STANDARD_KPI_NAMES),
        )
        .order_by(KpiTimeseries.extracted_at.desc())
    )

    summary: dict[str, dict[str, Any]] = {}
    for row in result.scalars().all():
        if row.kpi_name in summary:
            continue  # newest-first query -- first hit per name is the latest
        summary[row.kpi_name] = {
            "value": row.value,
            "unit": row.unit,
            "period": row.period,
            "citation": row.citation,
        }
    return summary


async def get_management_credibility_score(
    coverage_id: str, db: AsyncSession
) -> dict[str, Any] | None:
    """Extract a management credibility read from the latest quarterly update, if any."""
    result = await db.execute(
        select(ResearchOutput)
        .where(
            ResearchOutput.coverage_id == uuid.UUID(coverage_id),
            ResearchOutput.output_type == OutputTypeEnum.quarterly_update,
        )
        .order_by(ResearchOutput.generated_at.desc())
    )
    outputs = result.scalars().all()
    if not outputs:
        return None

    match = _MANAGEMENT_CREDIBILITY_RE.search(outputs[0].content)
    if match is None:
        return None

    return {"score": match.group(1).capitalize(), "quarters_tracked": len(outputs)}


async def save_bull_case(
    coverage_id: str,
    tenant_id: str,
    content: str,
    citations: list[dict[str, Any]],
    citation_coverage_pct: float,
    llm_used: str,
    tokens_used: int,
    db: AsyncSession,
) -> str:
    """INSERT into research_outputs with output_type="lynch_pitch"; return the output_id."""
    output = ResearchOutput(
        coverage_id=uuid.UUID(coverage_id),
        tenant_id=uuid.UUID(tenant_id),
        output_type=OutputTypeEnum.lynch_pitch,
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
        "lynch_pitch.bull_case_saved",
        coverage_id=coverage_id,
        output_id=str(output.id),
        citation_coverage_pct=citation_coverage_pct,
    )
    return str(output.id)
