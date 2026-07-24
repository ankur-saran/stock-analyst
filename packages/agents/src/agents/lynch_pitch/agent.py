"""The Lynch Pitch: answers "why would I own this stock?" in 8 fixed questions.

Grounded entirely in the coverage's own uploaded filings -- the six RAG
queries below are the agent's *only* window onto the company, run
concurrently via ``asyncio.gather`` since they're independent lookups against
the same collection. Every factual claim the LLM makes must carry an exact
quote or say "Not found in uploaded documents."; ``_parse_pitch_output`` is
where that discipline gets checked mechanically before the pitch is saved and
handed to the Citation Enforcer for the real (95%) gate.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from rag.retrieval.hybrid_retriever import RetrievedChunk
from shared.models import Coverage
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shared.base_agent import BaseAgent
from agents.shared.citation_enforcer import CITATION_PATTERN
from agents.shared.message import AgentMessage, AgentOutput, AgentType, LLMTier

from agents.lynch_pitch.prompts import LYNCH_PITCH_SYSTEM_PROMPT
from agents.lynch_pitch.schemas import AnswerWithCitation, CompanyType, LynchPitch
from agents.lynch_pitch.tools import (
    get_financial_summary,
    get_management_credibility_score,
    save_bull_case,
)

_RAG_QUERIES = (
    "business model revenue how does the company make money",
    "gross margin operating margin profitability",
    "balance sheet debt cash free cash flow",
    "competitive advantage moat differentiation",
    "risks risk factors threats",
    "growth drivers expansion opportunities",
)

_QUESTION_HEADER_RE = re.compile(r"^###\s*Q(\d+):\s*(.+)$", re.MULTILINE)
_NOT_FOUND_RE = re.compile(r"[^.\n]*not found in uploaded documents\.?", re.IGNORECASE)
_CLAIM_VERB_RE = re.compile(r"\b(?:is|are|was|were|has|have|had)\b", re.IGNORECASE)

# Ordered so a more specific phrase ("fast grower") never gets shadowed by a
# substring of a less specific one -- none of these six actually overlap, but
# the order still documents which phrase wins if the LLM ever writes two.
_COMPANY_TYPE_PHRASES: tuple[tuple[str, CompanyType], ...] = (
    ("slow grower", CompanyType.SLOW_GROWER),
    ("stalwart", CompanyType.STALWART),
    ("fast grower", CompanyType.FAST_GROWER),
    ("cyclical", CompanyType.CYCLICAL),
    ("turnaround", CompanyType.TURNAROUND),
    ("asset play", CompanyType.ASSET_PLAY),
)


class LynchPitchAgent(BaseAgent):
    agent_type = AgentType.LYNCH_PITCH

    async def _execute(self, message: AgentMessage) -> AgentOutput:
        coverage_id = message.coverage_id
        tenant_id = message.tenant_id

        results = await self._run_rag_searches(tenant_id, coverage_id)
        fin_summary = await get_financial_summary(coverage_id, self.db)
        cred_score = await get_management_credibility_score(coverage_id, self.db)
        company_info = await self._get_company_info(coverage_id, self.db)

        context = self._build_rag_context(results, _RAG_QUERIES)
        retry_prompt = message.payload.get("retry_prompt")

        messages = [
            {"role": "system", "content": LYNCH_PITCH_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": self._build_user_message(
                    company_info, context, fin_summary, cred_score, retry_prompt
                ),
            },
        ]

        content, model_used, tokens = await self._call_llm(
            messages=messages,
            tier=LLMTier.PRIMARY,
            max_tokens=6000,
        )

        pitch = self._parse_pitch_output(content, coverage_id, company_info, model_used)

        output_id = await save_bull_case(
            coverage_id,
            tenant_id,
            content,
            pitch.all_citations,
            pitch.citation_coverage_pct,
            model_used,
            tokens,
            self.db,
        )

        return AgentOutput(
            message_id=output_id,
            agent=AgentType.LYNCH_PITCH,
            task_id=message.task_id,
            coverage_id=coverage_id,
            tenant_id=tenant_id,
            content=content,
            citations=pitch.all_citations,
            citation_coverage_pct=pitch.citation_coverage_pct,
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,  # overwritten by BaseAgent.run() once _execute returns
        )

    async def _run_rag_searches(
        self, tenant_id: str, coverage_id: str
    ) -> list[list[RetrievedChunk]]:
        if self.retriever is None:
            raise ValueError("LynchPitchAgent requires a HybridRetriever — none was provided")
        retriever = self.retriever
        return await asyncio.gather(
            *[
                retriever.retrieve(q, tenant_id, coverage_id, top_k=5, rerank_top_n=3)
                for q in _RAG_QUERIES
            ]
        )

    def _build_rag_context(
        self, results: list[list[RetrievedChunk]], queries: tuple[str, ...]
    ) -> str:
        context_parts: list[str] = []
        seen_chunk_ids: set[str] = set()
        for query, chunks in zip(queries, results):
            context_parts.append(f"\nEVIDENCE FOR '{query}':")
            for chunk in chunks:
                if chunk.chunk_id in seen_chunk_ids:
                    continue
                seen_chunk_ids.add(chunk.chunk_id)
                doc_name = chunk.metadata.get("document_name", "Unknown")
                section = chunk.metadata.get("section_name", "Unknown Section")
                context_parts.append(f'[{doc_name}, {section}]: "{chunk.content[:500]}"')
        return "\n".join(context_parts)

    def _build_user_message(
        self,
        company_info: dict[str, str],
        context: str,
        fin_summary: dict[str, Any],
        cred_score: dict[str, Any] | None,
        retry_prompt: str | None,
    ) -> str:
        parts = [
            f"Company: {company_info['company_name']} ({company_info['ticker']})",
            f"\nPre-computed financial summary (verify against documents):\n{json.dumps(fin_summary, indent=2)}",
        ]
        if cred_score:
            parts.append(f"\nManagement credibility from prior quarters: {json.dumps(cred_score)}")
        parts.append(f"\nDocument evidence base:\n{context}")
        if retry_prompt:
            parts.append(f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION. Fix these issues:\n{retry_prompt}")
        parts.append("\nNow answer all 8 questions using ONLY the evidence above.")
        return "\n".join(parts)

    def _parse_pitch_output(
        self, content: str, coverage_id: str, company_info: dict[str, str], llm_used: str
    ) -> LynchPitch:
        answers: list[AnswerWithCitation] = []
        all_citations: list[dict[str, Any]] = []
        company_type: CompanyType | None = None

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

            if question_number == 5:
                company_type = self._detect_company_type(body)

        if company_type is None:
            raise ValueError("Q5 (company type) was not found in the LLM output")

        return LynchPitch(
            coverage_id=coverage_id,
            company_name=company_info["company_name"],
            ticker=company_info["ticker"],
            answers=answers,
            company_type=company_type,
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

    def _detect_company_type(self, q5_text: str) -> CompanyType:
        lowered = q5_text.lower()
        for phrase, company_type in _COMPANY_TYPE_PHRASES:
            if phrase in lowered:
                return company_type
        raise ValueError(f"Could not detect company type from Q5 answer: {q5_text[:100]!r}")

    async def _get_company_info(self, coverage_id: str, db: AsyncSession) -> dict[str, str]:
        coverage = await db.get(Coverage, uuid.UUID(coverage_id))
        if coverage is None:
            raise ValueError(f"Coverage {coverage_id} not found")
        return {"ticker": coverage.ticker, "company_name": coverage.company_name}
