"""The Earnings Monitor: compares prior guidance to actual results,
quote-for-quote, on a new earnings filing.

Unlike Lynch Pitch/Munger Invert, this agent validates its own output against
the Citation Enforcer *inside* ``_execute`` rather than relying on a
downstream LangGraph node -- ``update_credibility_score`` and triggering the
KPI Tracker are both gated on "did this pass Citation Enforcer", and there's
no separate node wired for quarterly updates yet to do that gating. Requires
both a new filing and at least one prior 10-Q/10-K to compare against;
either missing returns ``error="PREREQUISITE_MISSING"`` without calling the LLM.
"""
from __future__ import annotations

import asyncio
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from rag.retrieval.hybrid_retriever import HybridRetriever, RetrievedChunk
from shared.models import Coverage, Document, IngestStatusEnum, Industry
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shared.base_agent import BaseAgent
from agents.shared.citation_enforcer import CITATION_PATTERN, CitationEnforcer
from agents.shared.message import AgentMessage, AgentOutput, AgentType, LLMTier

from agents.kpi_tracker.tools import get_kpi_list_for_industry

from agents.earnings_monitor.prompts import EARNINGS_MONITOR_SYSTEM_PROMPT
from agents.earnings_monitor.schemas import (
    CredibilityVerdict,
    ExecutionVerdict,
    MomentumVerdict,
    QuarterlySection,
    QuarterlyUpdate,
)
from agents.earnings_monitor.tools import (
    compare_management_language,
    save_quarterly_update,
    trigger_kpi_tracker,
    update_credibility_score,
)

_PRIOR_GUIDANCE_QUERIES = (
    "guidance outlook expects next quarter next year",
    "management commentary strategy priorities capital allocation",
)
_CURRENT_RESULTS_QUERIES = (
    "revenue net income earnings per share results",
    "gross margin operating margin",
    "key performance indicators operating metrics",
)

_SECTION_HEADER_RE = re.compile(r"^##\s*SECTION\s*(\d+):\s*(.+)$", re.MULTILINE)
_FINAL_SUMMARY_RE = re.compile(r"^##\s*FINAL SUMMARY\s*$", re.MULTILINE)
_EXECUTION_RE = re.compile(r"Execution vs expectations:\s*(Improving|Stable|Deteriorating)", re.IGNORECASE)
_CREDIBILITY_RE = re.compile(r"Management credibility:\s*(Strong|Mixed|Weak)", re.IGNORECASE)
_MOMENTUM_RE = re.compile(
    r"Business momentum(?:\s*vs\s*last\s*year)?:\s*(Better|Same|Worse)", re.IGNORECASE
)
_CLAIM_VERB_RE = re.compile(r"\b(?:is|are|was|were|has|have|had)\b", re.IGNORECASE)


class EarningsMonitorAgent(BaseAgent):
    agent_type = AgentType.EARNINGS_MONITOR

    async def _execute(self, message: AgentMessage) -> AgentOutput:
        coverage_id = message.coverage_id
        tenant_id = message.tenant_id

        new_document_id = message.payload.get("new_document_id")
        if not new_document_id:
            return self._prerequisite_missing(message, "new_document_id not provided in payload")

        new_document = await self.db.get(Document, uuid.UUID(new_document_id))
        if (
            new_document is None
            or str(new_document.coverage_id) != coverage_id
            or new_document.ingest_status != IngestStatusEnum.indexed
        ):
            return self._prerequisite_missing(message, "new document not found or not yet indexed")

        prior_documents = await self._get_prior_documents(coverage_id, new_document_id, self.db)
        if not prior_documents:
            return self._prerequisite_missing(
                message, "no prior indexed 10-Q/10-K documents found to compare against"
            )

        company_info, industry_name = await self._get_company_and_industry(coverage_id, self.db)
        kpi_names = get_kpi_list_for_industry(industry_name)

        retriever = self._require_retriever()
        prior_ids_filter = {
            "must": [{"key": "document_id", "match": {"any": [str(d.id) for d in prior_documents]}}]
        }
        current_id_filter = {
            "must": [{"key": "document_id", "match": {"value": str(new_document.id)}}]
        }

        prior_results, current_results, compare_context = await asyncio.gather(
            asyncio.gather(
                *[
                    retriever.retrieve(q, tenant_id, coverage_id, top_k=5, rerank_top_n=3, filters=prior_ids_filter)
                    for q in _PRIOR_GUIDANCE_QUERIES
                ]
            ),
            asyncio.gather(
                *[
                    retriever.retrieve(q, tenant_id, coverage_id, top_k=5, rerank_top_n=3, filters=current_id_filter)
                    for q in _CURRENT_RESULTS_QUERIES
                ]
            ),
            compare_management_language(coverage_id, str(new_document.id), tenant_id, retriever),
        )

        context = self._build_context(prior_results, current_results, compare_context)
        retry_prompt = message.payload.get("retry_prompt")

        messages = [
            {"role": "system", "content": EARNINGS_MONITOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_message(
                    company_info, kpi_names, context, retry_prompt
                ),
            },
        ]

        content, model_used, tokens = await self._call_llm(
            messages=messages,
            tier=LLMTier.PRIMARY,
            max_tokens=7000,
        )

        update = self._parse_quarterly_output(content, coverage_id, company_info, model_used)

        draft_output = AgentOutput(
            message_id=str(uuid.uuid4()),
            agent=AgentType.EARNINGS_MONITOR,
            task_id=message.task_id,
            coverage_id=coverage_id,
            tenant_id=tenant_id,
            content=content,
            citations=update.all_citations,
            citation_coverage_pct=update.citation_coverage_pct,
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,
        )

        enforcer = CitationEnforcer(retriever=retriever)
        validation = await enforcer.validate(draft_output, tenant_id, coverage_id)

        output_id = await save_quarterly_update(
            coverage_id,
            tenant_id,
            content,
            update.all_citations,
            validation.citation_coverage_pct,
            validation.approved,
            validation.enforcer_status,
            model_used,
            tokens,
            self.db,
        )

        if validation.approved:
            await update_credibility_score(
                coverage_id, new_document.period, update.management_credibility.value, self.db
            )
            await trigger_kpi_tracker(coverage_id, tenant_id, str(new_document.id), self.db)

        return AgentOutput(
            message_id=output_id,
            agent=AgentType.EARNINGS_MONITOR,
            task_id=message.task_id,
            coverage_id=coverage_id,
            tenant_id=tenant_id,
            content=content,
            citations=update.all_citations,
            citation_coverage_pct=validation.citation_coverage_pct,
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,  # overwritten by BaseAgent.run() once _execute returns
            approved_by_enforcer=validation.approved,
            enforcer_status=validation.enforcer_status,
        )

    def _prerequisite_missing(self, message: AgentMessage, reason: str) -> AgentOutput:
        return AgentOutput(
            message_id=str(uuid.uuid4()),
            agent=AgentType.EARNINGS_MONITOR,
            task_id=message.task_id,
            coverage_id=message.coverage_id,
            tenant_id=message.tenant_id,
            content=f"PREREQUISITE_MISSING: {reason}",
            citations=[],
            citation_coverage_pct=0.0,
            llm_used="",
            tokens_used=0,
            latency_ms=0,
            approved_by_enforcer=False,
            enforcer_status="failed",
            error="PREREQUISITE_MISSING",
        )

    def _require_retriever(self) -> HybridRetriever:
        if self.retriever is None:
            raise ValueError("EarningsMonitorAgent requires a HybridRetriever — none was provided")
        return self.retriever

    async def _get_prior_documents(
        self, coverage_id: str, new_document_id: str, db: AsyncSession
    ) -> list[Document]:
        result = await db.execute(
            select(Document).where(
                Document.coverage_id == uuid.UUID(coverage_id),
                Document.filing_type.in_(["10-Q", "10-K"]),
                Document.id != uuid.UUID(new_document_id),
                Document.ingest_status == IngestStatusEnum.indexed,
            )
        )
        return list(result.scalars().all())

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

    def _build_context(
        self,
        prior_results: list[list[RetrievedChunk]],
        current_results: list[list[RetrievedChunk]],
        compare_context: str,
    ) -> str:
        context_parts: list[str] = ["=== PRIOR GUIDANCE EVIDENCE (filings before the current one) ==="]
        seen_chunk_ids: set[str] = set()

        for query, chunks in zip(_PRIOR_GUIDANCE_QUERIES, prior_results):
            context_parts.append(f"\nEVIDENCE FOR '{query}':")
            for chunk in chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk.chunk_id)
                doc_name = chunk.metadata.get("document_name", "Unknown")
                section = chunk.metadata.get("section_name", "Unknown Section")
                context_parts.append(f'[{doc_name}, {section}]: "{chunk.content[:500]}"')

        context_parts.append("\n=== CURRENT RESULTS EVIDENCE (the new filing) ===")
        for query, chunks in zip(_CURRENT_RESULTS_QUERIES, current_results):
            context_parts.append(f"\nEVIDENCE FOR '{query}':")
            for chunk in chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk.chunk_id)
                doc_name = chunk.metadata.get("document_name", "Unknown")
                section = chunk.metadata.get("section_name", "Unknown Section")
                context_parts.append(f'[{doc_name}, {section}]: "{chunk.content[:500]}"')

        context_parts.append(f"\n=== MANAGEMENT LANGUAGE HISTORY ===\n{compare_context}")
        return "\n".join(context_parts)

    def _build_user_message(
        self,
        company_info: dict[str, str],
        kpi_names: list[str],
        context: str,
        retry_prompt: str | None,
    ) -> str:
        parts = [
            f"Company: {company_info['company_name']} ({company_info['ticker']})",
            f"\nIndustry KPI list for Section 2: {', '.join(kpi_names)}",
            f"\nDocument evidence base:\n{context}",
        ]
        if retry_prompt:
            parts.append(f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION. Fix these issues:\n{retry_prompt}")
        parts.append("\nNow produce all 3 sections and the FINAL SUMMARY using ONLY the evidence above.")
        return "\n".join(parts)

    def _parse_quarterly_output(
        self, content: str, coverage_id: str, company_info: dict[str, str], llm_used: str
    ) -> QuarterlyUpdate:
        headers = list(_SECTION_HEADER_RE.finditer(content))
        final_summary_match = _FINAL_SUMMARY_RE.search(content)
        end_of_last_section = final_summary_match.start() if final_summary_match else len(content)

        sections: list[QuarterlySection] = []
        all_citations: list[dict[str, Any]] = []
        for i, header in enumerate(headers):
            body_start = header.end()
            body_end = headers[i + 1].start() if i + 1 < len(headers) else end_of_last_section
            body = content[body_start:body_end].strip()

            citations = [
                {"doc": d, "section": s, "quote": q} for d, s, q in CITATION_PATTERN.findall(body)
            ]
            all_citations.extend(citations)
            sections.append(
                QuarterlySection(
                    section_number=int(header.group(1)),
                    section_name=header.group(2).strip(),
                    content=body,
                    citations=citations,
                )
            )

        if final_summary_match is None:
            raise ValueError("FINAL SUMMARY section not found in LLM output")
        final_body = content[final_summary_match.end():]

        execution_match = _EXECUTION_RE.search(final_body)
        credibility_match = _CREDIBILITY_RE.search(final_body)
        momentum_match = _MOMENTUM_RE.search(final_body)
        if not (execution_match and credibility_match and momentum_match):
            raise ValueError("FINAL SUMMARY is missing one or more of the three required verdict lines")

        return QuarterlyUpdate(
            coverage_id=coverage_id,
            company_name=company_info["company_name"],
            ticker=company_info["ticker"],
            sections=sections,
            execution_vs_expectations=ExecutionVerdict(execution_match.group(1).capitalize()),
            management_credibility=CredibilityVerdict(credibility_match.group(1).capitalize()),
            business_momentum=MomentumVerdict(momentum_match.group(1).capitalize()),
            all_citations=all_citations,
            citation_coverage_pct=self._content_coverage(content),
            word_count=len(content.split()),
            generated_at=datetime.now(timezone.utc),
            llm_used=llm_used,
        )

    def _content_coverage(self, text: str) -> float:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        claim_paragraphs = [
            p
            for p in paragraphs
            if (any(c.isdigit() for c in p) or _CLAIM_VERB_RE.search(p))
            and "not found in uploaded documents" not in p.lower()
        ]
        cited_paragraphs = [p for p in claim_paragraphs if CITATION_PATTERN.search(p)]
        return 1.0 if not claim_paragraphs else len(cited_paragraphs) / len(claim_paragraphs)
