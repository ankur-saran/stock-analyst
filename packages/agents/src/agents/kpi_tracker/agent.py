"""The KPI Tracker: extracts and maintains time-series KPIs from every filing.

Unlike the reasoning agents, this is a structured-extraction agent -- one
JSON-mode call per not-yet-extracted document, against the SECONDARY tier
(GPT-4o), asking only for the fixed KPI vocabulary this coverage's industry
defines (``infra/kpi_definitions.yaml``). There's no citation-coverage prose
to check here: every extracted value already carries its own document/
section/quote citation straight into ``kpi_timeseries``, so this agent
self-approves its summary output rather than routing through the Citation
Enforcer's prose-oriented checks.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

import structlog
from rag.ingestion.parsers.financial_normalizer import FinancialNormalizer
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.models import Coverage, Industry, PeriodTypeEnum
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shared.base_agent import BaseAgent
from agents.shared.message import AgentMessage, AgentOutput, AgentType, LLMTier

from agents.kpi_tracker.prompts import KPI_EXTRACTION_SYSTEM_PROMPT
from agents.kpi_tracker.schemas import ExtractedKPI
from agents.kpi_tracker.tools import (
    compute_yoy_change,
    gather_document_context,
    get_kpi_list_for_industry,
    get_unextracted_documents,
    upsert_kpi_timeseries,
)

logger = structlog.get_logger()

_JSON_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class KPITrackerAgent(BaseAgent):
    agent_type = AgentType.KPI_TRACKER

    async def _execute(self, message: AgentMessage) -> AgentOutput:
        coverage_id = message.coverage_id
        tenant_id = message.tenant_id
        normalizer = FinancialNormalizer()

        company_info, industry_name = await self._get_company_and_industry(coverage_id, self.db)
        kpi_names = get_kpi_list_for_industry(industry_name)
        documents = await get_unextracted_documents(coverage_id, self.db)

        all_citations: list[dict[str, Any]] = []
        doc_summaries: list[str] = []
        total_upserted = 0
        tokens_total = 0
        last_model_used = ""

        for document in documents:
            context = await gather_document_context(
                document, tenant_id, coverage_id, kpi_names, self._require_retriever()
            )
            if not context.strip():
                continue

            messages = [
                {"role": "system", "content": KPI_EXTRACTION_SYSTEM_PROMPT},
                {"role": "user", "content": self._build_user_message(kpi_names, context)},
            ]
            content, model_used, tokens = await self._call_llm(
                messages=messages,
                tier=LLMTier.SECONDARY,
                max_tokens=3000,
                response_format={"type": "json_object"},
            )
            tokens_total += tokens
            last_model_used = model_used

            extracted = self._parse_extraction(content)
            if not extracted:
                continue

            kpi_data: list[dict[str, Any]] = []
            for item in extracted:
                normalized = self._normalize_extracted(item, normalizer)
                if normalized is None:
                    continue
                kpi_data.append(normalized)
                all_citations.append(
                    {"doc": item.document_name, "section": item.section, "quote": item.exact_quote}
                )

            if not kpi_data:
                continue

            upserted = await upsert_kpi_timeseries(coverage_id, kpi_data, self.db)
            total_upserted += upserted
            doc_summaries.append(f"- {document.file_name}: {upserted} KPI value(s) upserted")

        yoy_lines = await self._build_yoy_summary(coverage_id, kpi_names)

        content = self._build_summary(company_info, doc_summaries, yoy_lines, total_upserted)

        return AgentOutput(
            message_id=str(uuid.uuid4()),
            agent=AgentType.KPI_TRACKER,
            task_id=message.task_id,
            coverage_id=coverage_id,
            tenant_id=tenant_id,
            content=content,
            citations=all_citations,
            citation_coverage_pct=1.0,
            llm_used=last_model_used,
            tokens_used=tokens_total,
            latency_ms=0,  # overwritten by BaseAgent.run() once _execute returns
            approved_by_enforcer=True,
            enforcer_status="approved",
        )

    def _require_retriever(self) -> HybridRetriever:
        if self.retriever is None:
            raise ValueError("KPITrackerAgent requires a HybridRetriever — none was provided")
        return self.retriever

    async def _get_company_and_industry(
        self, coverage_id: str, db: AsyncSession
    ) -> tuple[dict[str, str], str | None]:
        coverage = await db.get(Coverage, uuid.UUID(coverage_id))
        if coverage is None:
            raise ValueError(f"Coverage {coverage_id} not found")

        industry_name: str | None = None
        if coverage.industry_id is not None:
            industry = await db.get(Industry, coverage.industry_id)
            industry_name = industry.name if industry is not None else None

        return {"ticker": coverage.ticker, "company_name": coverage.company_name}, industry_name

    def _build_user_message(self, kpi_names: list[str], context: str) -> str:
        return (
            f"Extract these KPIs from the document: {', '.join(kpi_names)}\n\n"
            f"For each one, provide the exact quote and the citation fields as instructed.\n\n"
            f"EVIDENCE:\n{context}"
        )

    def _parse_extraction(self, content: str) -> list[ExtractedKPI]:
        cleaned = _JSON_FENCE_RE.sub("", content.strip())
        try:
            body = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("kpi_tracker.invalid_json", content=cleaned[:200])
            return []

        raw_items = body.get("kpis", []) if isinstance(body, dict) else body
        items: list[ExtractedKPI] = []
        for raw in raw_items:
            try:
                items.append(ExtractedKPI(**raw))
            except Exception as exc:  # noqa: BLE001 - one bad item shouldn't drop the batch
                logger.warning("kpi_tracker.invalid_item", item=raw, error=str(exc))
        return items

    def _normalize_extracted(
        self, item: ExtractedKPI, normalizer: FinancialNormalizer
    ) -> dict[str, Any] | None:
        normalized_value = normalizer.normalize_value(item.raw_value)
        if normalized_value.confidence == 0.0:
            logger.warning("kpi_tracker.unnormalizable_value", raw=item.raw_value, kpi=item.kpi_name)
            return None

        try:
            normalized_period = normalizer.normalize_period(item.period)
        except ValueError:
            logger.warning("kpi_tracker.unnormalizable_period", raw=item.period, kpi=item.kpi_name)
            return None

        value = -normalized_value.numeric_value if normalized_value.is_negative else normalized_value.numeric_value

        return {
            "kpi_name": item.kpi_name,
            "period": normalized_period.period_label,
            "period_type": PeriodTypeEnum(normalized_period.period_type),
            "value": value,
            "unit": normalized_value.unit,
            "citation": {
                "document_name": item.document_name,
                "section": item.section,
                "page_number": item.page_number,
                "exact_quote": item.exact_quote,
                "raw_value": item.raw_value,
            },
        }

    async def _build_yoy_summary(self, coverage_id: str, kpi_names: list[str]) -> list[str]:
        lines: list[str] = []
        for kpi_name in kpi_names:
            yoy = await compute_yoy_change(coverage_id, kpi_name, self.db)
            if yoy is None:
                continue
            pct = yoy["yoy_change_pct"]
            pct_str = f"{pct:+.1f}%" if pct is not None else "n/a"
            lines.append(f"- {kpi_name}: {yoy['prior_period']} -> {yoy['current_period']}: {pct_str}")
        return lines

    def _build_summary(
        self,
        company_info: dict[str, str],
        doc_summaries: list[str],
        yoy_lines: list[str],
        total_upserted: int,
    ) -> str:
        parts = [
            f"# KPI Tracker Update: {company_info['company_name']} ({company_info['ticker']})",
            f"\n{total_upserted} KPI value(s) upserted across {len(doc_summaries)} document(s).",
        ]
        if doc_summaries:
            parts.append("\n## Documents Processed\n" + "\n".join(doc_summaries))
        if yoy_lines:
            parts.append("\n## Year-over-Year Changes\n" + "\n".join(yoy_lines))
        if not doc_summaries:
            parts.append("\nNo new documents required KPI extraction.")
        return "\n".join(parts)
