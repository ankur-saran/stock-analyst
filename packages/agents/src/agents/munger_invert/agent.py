"""The Munger Invert: adversarial bear case -- INVALIDATES the thesis using
the same documents Lynch Pitch draws from.

Structurally identical to :class:`~agents.lynch_pitch.agent.LynchPitchAgent`:
same RAG-then-single-LLM-call shape, same citation-discipline parsing, same
downstream Citation Enforcer gate. What differs is the evidence mix (general
queries plus two section-filtered searches that target risk factors and
footnote disclosures specifically) and the prompt's goal -- invalidation, not
balance. Adversarial tone never excuses a missing citation: the Citation
Enforcer's checks run identically regardless of which agent produced the
content.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from rag.retrieval.hybrid_retriever import HybridRetriever, RetrievedChunk
from shared.models import Coverage
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shared.base_agent import BaseAgent
from agents.shared.citation_enforcer import CITATION_PATTERN
from agents.shared.message import AgentMessage, AgentOutput, AgentType, LLMTier

from agents.lynch_pitch.tools import get_financial_summary, get_management_credibility_score

from agents.munger_invert.prompts import MUNGER_INVERT_SYSTEM_PROMPT
from agents.munger_invert.schemas import AnswerWithCitation, MungerCase
from agents.munger_invert.tools import (
    compare_narrative_to_data,
    save_bear_case,
    search_footnotes,
    search_risk_factors,
)

# Revenue is the one KPI every coverage should have a timeseries for, so it's
# the default narrative-vs-data check surfaced for Q7 -- not exhaustive, but
# always available rather than requiring the caller to know the KPI vocabulary.
_NARRATIVE_CHECK_KPI = "revenue"

# General-purpose evidence the bear case needs on top of the two
# section-filtered searches (risk factors, footnotes) run separately below.
_RAG_QUERIES = (
    "business model revenue how does the company make money",
    "gross margin operating margin profitability",
    "debt covenant credit facility revolving credit",
    "goodwill impairment writedown restructuring",
    "guidance revision lowered outlook missed",
)

_QUESTION_HEADER_RE = re.compile(r"^###\s*Q(\d+):\s*(.+)$", re.MULTILINE)
_NOT_FOUND_RE = re.compile(r"[^.\n]*not found in uploaded documents\.?", re.IGNORECASE)
_CLAIM_VERB_RE = re.compile(r"\b(?:is|are|was|were|has|have|had)\b", re.IGNORECASE)


class MungerInvertAgent(BaseAgent):
    agent_type = AgentType.MUNGER_INVERT

    async def _execute(self, message: AgentMessage) -> AgentOutput:
        coverage_id = message.coverage_id
        tenant_id = message.tenant_id

        general_results, risk_chunks, footnote_chunks = await asyncio.gather(
            self._run_rag_searches(tenant_id, coverage_id),
            search_risk_factors(coverage_id, tenant_id, self._require_retriever()),
            search_footnotes(coverage_id, tenant_id, self._require_retriever()),
        )
        fin_summary = await get_financial_summary(coverage_id, self.db)
        cred_score = await get_management_credibility_score(coverage_id, self.db)
        narrative_check = await compare_narrative_to_data(coverage_id, _NARRATIVE_CHECK_KPI, self.db)
        company_info = await self._get_company_info(coverage_id, self.db)

        context = self._build_context(general_results, risk_chunks, footnote_chunks)
        retry_prompt = message.payload.get("retry_prompt")

        messages = [
            {"role": "system", "content": MUNGER_INVERT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_message(
                    company_info, context, fin_summary, cred_score, narrative_check, retry_prompt
                ),
            },
        ]

        content, model_used, tokens = await self._call_llm(
            messages=messages,
            tier=LLMTier.PRIMARY,
            max_tokens=6000,
        )

        case = self._parse_invert_output(content, coverage_id, company_info, model_used)

        output_id = await save_bear_case(
            coverage_id,
            tenant_id,
            content,
            case.all_citations,
            case.citation_coverage_pct,
            model_used,
            tokens,
            self.db,
        )

        return AgentOutput(
            message_id=output_id,
            agent=AgentType.MUNGER_INVERT,
            task_id=message.task_id,
            coverage_id=coverage_id,
            tenant_id=tenant_id,
            content=content,
            citations=case.all_citations,
            citation_coverage_pct=case.citation_coverage_pct,
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,  # overwritten by BaseAgent.run() once _execute returns
        )

    def _require_retriever(self) -> HybridRetriever:
        if self.retriever is None:
            raise ValueError("MungerInvertAgent requires a HybridRetriever — none was provided")
        return self.retriever

    async def _run_rag_searches(
        self, tenant_id: str, coverage_id: str
    ) -> list[list[RetrievedChunk]]:
        retriever = self._require_retriever()
        return await asyncio.gather(
            *[
                retriever.retrieve(q, tenant_id, coverage_id, top_k=5, rerank_top_n=3)
                for q in _RAG_QUERIES
            ]
        )

    def _build_context(
        self,
        general_results: list[list[RetrievedChunk]],
        risk_chunks: list[dict[str, Any]],
        footnote_chunks: list[dict[str, Any]],
    ) -> str:
        context_parts: list[str] = []
        seen_chunk_ids: set[str] = set()

        for query, chunks in zip(_RAG_QUERIES, general_results):
            context_parts.append(f"\nEVIDENCE FOR '{query}':")
            for chunk in chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk.chunk_id)
                doc_name = chunk.metadata.get("document_name", "Unknown")
                section = chunk.metadata.get("section_name", "Unknown Section")
                context_parts.append(f'[{doc_name}, {section}]: "{chunk.content[:500]}"')

        for label, dict_chunks in (
            ("risk factors material risks litigation regulatory", risk_chunks),
            ("footnotes contingent liabilities off-balance-sheet operating leases", footnote_chunks),
        ):
            context_parts.append(f"\nEVIDENCE FOR '{label}':")
            for chunk in dict_chunks:
                chunk_id = chunk["chunk_id"]
                if chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk_id)
                doc_name = chunk["metadata"].get("document_name", "Unknown")
                section = chunk["metadata"].get("section_name", "Unknown Section")
                context_parts.append(f'[{doc_name}, {section}]: "{chunk["content"][:500]}"')

        return "\n".join(context_parts)

    def _build_user_message(
        self,
        company_info: dict[str, str],
        context: str,
        fin_summary: dict[str, Any],
        cred_score: dict[str, Any] | None,
        narrative_check: dict[str, Any] | None,
        retry_prompt: str | None,
    ) -> str:
        parts = [
            f"Company: {company_info['company_name']} ({company_info['ticker']})",
            f"\nPre-computed financial summary (verify against documents):\n{json.dumps(fin_summary, indent=2)}",
        ]
        if cred_score:
            parts.append(f"\nManagement credibility from prior quarters: {json.dumps(cred_score)}")
        if narrative_check:
            parts.append(
                f"\nNarrative-vs-data check for {_NARRATIVE_CHECK_KPI} "
                f"(use this for Q7 if it shows a divergence): {json.dumps(narrative_check)}"
            )
        parts.append(f"\nDocument evidence base:\n{context}")
        if retry_prompt:
            parts.append(f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION. Fix these issues:\n{retry_prompt}")
        parts.append("\nNow answer all 8 questions using ONLY the evidence above. Invalidate the thesis.")
        return "\n".join(parts)

    def _parse_invert_output(
        self, content: str, coverage_id: str, company_info: dict[str, str], llm_used: str
    ) -> MungerCase:
        answers: list[AnswerWithCitation] = []
        all_citations: list[dict[str, Any]] = []

        headers = list(_QUESTION_HEADER_RE.finditer(content))
        for i, header in enumerate(headers):
            body_start = header.end()
            body_end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
            body = content[body_start:body_end].strip()
            question_number = int(header.group(1))

            citations = [
                {"doc": d, "section": s, "quote": q} for d, s, q in CITATION_PATTERN.findall(body)
            ]
            all_citations.extend(citations)
            not_found_items = [item.strip() for item in _NOT_FOUND_RE.findall(body)]

            answers.append(
                AnswerWithCitation(
                    question_number=question_number,
                    question_text=header.group(2).strip(),
                    answer_text=body,
                    citations=citations,
                    citation_coverage_pct=self._answer_coverage(body),
                    not_found_items=not_found_items,
                )
            )

        return MungerCase(
            coverage_id=coverage_id,
            company_name=company_info["company_name"],
            ticker=company_info["ticker"],
            answers=answers,
            all_citations=all_citations,
            citation_coverage_pct=self._answer_coverage(content),
            word_count=len(content.split()),
            generated_at=datetime.now(timezone.utc),
            llm_used=llm_used,
        )

    def _answer_coverage(self, text: str) -> float:
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        claim_paragraphs = [
            p
            for p in paragraphs
            if (any(c.isdigit() for c in p) or _CLAIM_VERB_RE.search(p))
            and "not found in uploaded documents" not in p.lower()
        ]
        cited_paragraphs = [p for p in claim_paragraphs if CITATION_PATTERN.search(p)]
        return 1.0 if not claim_paragraphs else len(cited_paragraphs) / len(claim_paragraphs)

    async def _get_company_info(self, coverage_id: str, db: AsyncSession) -> dict[str, str]:
        coverage = await db.get(Coverage, uuid.UUID(coverage_id))
        if coverage is None:
            raise ValueError(f"Coverage {coverage_id} not found")
        return {"ticker": coverage.ticker, "company_name": coverage.company_name}
