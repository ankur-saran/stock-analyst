"""Tool functions callable by the KPI Tracker agent.

``load_kpi_definitions``/``resolve_industry_key`` turn a coverage's free-text
``Industry.name`` into the fixed KPI vocabulary in
``infra/kpi_definitions.yaml``, falling back to ``default`` for any industry
that isn't one of the named sectors (including no industry at all).
``get_unextracted_documents`` treats "has this document been KPI-extracted"
as "does any KpiTimeseries row for this coverage cite this document's file
name" rather than adding a new tracking column -- cheap to query and
self-healing if a document is re-ingested under the same name.
``upsert_kpi_timeseries`` is the one write this agent performs, and it must
stay idempotent: re-running extraction on the same document must never
duplicate a row or spuriously mark it restated.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Any

import structlog
import yaml  # type: ignore[import-untyped]
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.models import Document, IngestStatusEnum, KpiTimeseries, PeriodTypeEnum
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

# packages/agents/src/agents/kpi_tracker/tools.py -> repo root is 5 levels up.
_KPI_DEFINITIONS_PATH = Path(__file__).resolve().parents[5] / "infra" / "kpi_definitions.yaml"
_DEFAULT_INDUSTRY_KEY = "default"

_VALUE_TOLERANCE = 1e-6
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_YEAR_RE = re.compile(r"\d{4}")


@lru_cache(maxsize=1)
def load_kpi_definitions() -> dict[str, list[str]]:
    """Load and cache ``infra/kpi_definitions.yaml``'s industry -> KPI list mapping."""
    with open(_KPI_DEFINITIONS_PATH, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return {name: cfg["kpis"] for name, cfg in raw["industries"].items()}


def resolve_industry_key(industry_name: str | None) -> str:
    """Normalize a free-text industry name to a ``kpi_definitions.yaml`` key.

    Falls back to "default" whenever the coverage has no industry, or the
    industry name doesn't match one of the defined sectors.
    """
    definitions = load_kpi_definitions()
    if not industry_name:
        return _DEFAULT_INDUSTRY_KEY
    key = _NON_ALNUM_RE.sub("_", industry_name.strip().lower()).strip("_")
    return key if key in definitions else _DEFAULT_INDUSTRY_KEY


def get_kpi_list_for_industry(industry_name: str | None) -> list[str]:
    definitions = load_kpi_definitions()
    key = resolve_industry_key(industry_name)
    return definitions[key]


async def get_unextracted_documents(coverage_id: str, db: AsyncSession) -> list[Document]:
    """Indexed documents in this coverage with no KpiTimeseries citation yet."""
    extracted_result = await db.execute(
        select(KpiTimeseries.citation["document_name"].astext)
        .where(KpiTimeseries.coverage_id == uuid.UUID(coverage_id))
        .distinct()
    )
    extracted_names = {row[0] for row in extracted_result.all() if row[0] is not None}

    doc_result = await db.execute(
        select(Document).where(
            Document.coverage_id == uuid.UUID(coverage_id),
            Document.ingest_status == IngestStatusEnum.indexed,
        )
    )
    return [d for d in doc_result.scalars().all() if d.file_name not in extracted_names]


async def gather_document_context(
    document: Document, tenant_id: str, coverage_id: str, kpi_names: list[str], retriever: HybridRetriever
) -> str:
    """Retrieve evidence for each requested KPI, scoped to this one document."""
    queries = [kpi.replace("_", " ") for kpi in kpi_names]
    doc_filter = {"must": [{"key": "document_id", "match": {"value": str(document.id)}}]}

    results = await asyncio.gather(
        *[
            retriever.retrieve(
                q, tenant_id, coverage_id, top_k=3, rerank_top_n=2, filters=doc_filter
            )
            for q in queries
        ]
    )

    context_parts: list[str] = []
    seen_chunk_ids: set[str] = set()
    for query, chunks in zip(queries, results):
        context_parts.append(f"\nEVIDENCE FOR '{query}':")
        for chunk in chunks:
            if chunk.chunk_id in seen_chunk_ids:
                continue
            seen_chunk_ids.add(chunk.chunk_id)
            doc_name = chunk.metadata.get("document_name", document.file_name)
            section = chunk.metadata.get("section_name", "Unknown Section")
            page = chunk.metadata.get("page_number")
            context_parts.append(
                f'[document_name={doc_name}, section={section}, page_number={page}]: "{chunk.content[:800]}"'
            )
    return "\n".join(context_parts)


async def upsert_kpi_timeseries(
    coverage_id: str, kpi_data: list[dict[str, Any]], db: AsyncSession
) -> int:
    """Insert/restate KPI rows; idempotent for identical (coverage, kpi, period, value)."""
    upserted = 0
    for item in kpi_data:
        existing_result = await db.execute(
            select(KpiTimeseries)
            .where(
                KpiTimeseries.coverage_id == uuid.UUID(coverage_id),
                KpiTimeseries.kpi_name == item["kpi_name"],
                KpiTimeseries.period == item["period"],
            )
            .order_by(KpiTimeseries.extracted_at.desc())
        )
        existing = existing_result.scalars().first()

        if existing is not None and abs(existing.value - item["value"]) < _VALUE_TOLERANCE:
            continue  # identical value already recorded -- idempotent no-op

        is_restated = existing is not None
        restatement_note = (
            f"Restated from {existing.value} to {item['value']}"
            if existing is not None
            else None
        )

        db.add(
            KpiTimeseries(
                coverage_id=uuid.UUID(coverage_id),
                kpi_name=item["kpi_name"],
                period=item["period"],
                period_type=item["period_type"],
                value=item["value"],
                unit=item["unit"],
                citation=item["citation"],
                is_restated=is_restated,
                restatement_note=restatement_note,
            )
        )
        upserted += 1

    await db.commit()
    return upserted


async def compute_yoy_change(coverage_id: str, kpi_name: str, db: AsyncSession) -> dict[str, Any] | None:
    """YoY change between the two most recent annual data points for this KPI."""
    result = await db.execute(
        select(KpiTimeseries).where(
            KpiTimeseries.coverage_id == uuid.UUID(coverage_id),
            KpiTimeseries.kpi_name == kpi_name,
            KpiTimeseries.period_type == PeriodTypeEnum.annual,
        )
    )
    rows = list(result.scalars().all())
    if len(rows) < 2:
        return None

    def _year(row: KpiTimeseries) -> int:
        match = _YEAR_RE.search(row.period)
        return int(match.group()) if match else -1

    rows.sort(key=_year)
    prior, current = rows[-2], rows[-1]

    yoy_change_pct = (
        (current.value - prior.value) / abs(prior.value) * 100 if prior.value != 0 else None
    )

    return {
        "current_period": current.period,
        "prior_period": prior.period,
        "yoy_change_pct": yoy_change_pct,
    }
