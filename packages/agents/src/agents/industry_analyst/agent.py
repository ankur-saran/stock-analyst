"""The Industry Analyst: writes the once-per-industry primer every stock in
that industry's coverage reuses.

Unlike the per-coverage research agents, this one runs against no uploaded
filings at all by default — its evidence base is live web research (Tavily),
gathered before the single LLM call that synthesizes the full 6-section
primer using extended thinking. The output is stored directly on the shared
``industries`` row (no ``tenant_id``, no ``coverage_id`` scoping) since the
primer is deliberately shared across every tenant covering that industry.
"""
from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from agents.shared.base_agent import BaseAgent
from agents.shared.citation_enforcer import CITATION_PATTERN
from agents.shared.message import AgentMessage, AgentOutput, AgentType, LLMTier

from agents.industry_analyst.prompts import INDUSTRY_ANALYST_SYSTEM_PROMPT
from agents.industry_analyst.schemas import (
    IndustryPrimer,
    IndustryPrimerSection,
    InvestorSynthesisBullet,
)
from agents.industry_analyst.tools import save_industry_primer, web_search

# Section headers exactly as mandated by the system prompt — used to split
# the LLM's markdown output back into structured sections.
_SECTION_HEADER_RE = re.compile(r"^##\s*(\d+)\.\s*(.+)$", re.MULTILINE)
_SYNTHESIS_HEADER_RE = re.compile(r"^##\s*Investor Synthesis\s*$", re.MULTILINE)
_SYNTHESIS_BULLET_RE = re.compile(r"^-\s*(.+)$", re.MULTILINE)

# Order matches the five bullets mandated by the system prompt exactly.
_SYNTHESIS_TOPICS = [
    "core_economic_engine",
    "primary_growth_lever",
    "structural_constraint",
    "key_risk",
    "winning_companies",
]


class IndustryAnalystAgent(BaseAgent):
    agent_type = AgentType.INDUSTRY_ANALYST

    async def _execute(self, message: AgentMessage) -> AgentOutput:
        industry_name = message.payload["industry_name"]
        industry_id = message.payload["industry_id"]

        research_context = await self._gather_research(industry_name, industry_id)

        messages = [
            {"role": "system", "content": INDUSTRY_ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_message(industry_name, research_context)},
        ]

        content, model_used, tokens = await self._call_llm(
            messages=messages,
            tier=LLMTier.PRIMARY,
            max_tokens=8000,
            extended_thinking=True,
        )

        primer = self._parse_primer_output(content, industry_id, industry_name, model_used)

        await save_industry_primer(industry_id, content, primer.all_citations, model_used, self.db)

        return AgentOutput(
            message_id=str(uuid.uuid4()),
            agent=AgentType.INDUSTRY_ANALYST,
            task_id=message.task_id,
            coverage_id=message.coverage_id,
            tenant_id=message.tenant_id,
            content=content,
            citations=primer.all_citations,
            citation_coverage_pct=primer.confidence_score,
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,  # overwritten by BaseAgent.run() once _execute returns
        )

    async def _gather_research(self, industry_name: str, industry_id: str) -> str:
        queries = [
            f"{industry_name} industry economics business model revenue drivers",
            f"{industry_name} industry competitive landscape major players market structure",
            f"{industry_name} industry regulatory environment technology trends outlook",
        ]
        results = []
        for q in queries:
            search_results = await web_search(q, max_results=4)
            results.extend(search_results)

        context_parts = ["=== WEB RESEARCH CONTEXT ===\n"]
        for r in results[:10]:  # cap at 10 results
            context_parts.append(
                f"SOURCE: [{r['title']}, {r['url']}, {r.get('published_date', 'n/d')}]\n"
                f"CONTENT: {r['content'][:1000]}\n"
            )
        return "\n".join(context_parts)

    def _build_user_message(self, industry_name: str, research_context: str) -> str:
        return (
            f"Write a comprehensive industry primer for: {industry_name}\n\n"
            f"Use the following research as your primary evidence base. "
            f'Cite every claim using [Source Name, URL, Date]: "exact quote" format.\n\n'
            f"{research_context}"
        )

    def _parse_primer_output(
        self, content: str, industry_id: str, industry_name: str, llm_used: str
    ) -> IndustryPrimer:
        citations = [
            {"doc": d, "section": s, "quote": q} for d, s, q in CITATION_PATTERN.findall(content)
        ]

        sections = self._extract_sections(content)
        synthesis = self._extract_synthesis(content)
        word_count = len(content.split())

        total_paragraphs = len([p for p in content.split("\n\n") if p.strip()])
        cited_paragraphs = len(
            [p for p in content.split("\n\n") if p.strip() and CITATION_PATTERN.search(p)]
        )
        confidence = cited_paragraphs / max(total_paragraphs, 1)

        return IndustryPrimer(
            industry_id=industry_id,
            industry_name=industry_name,
            sections=sections,
            investor_synthesis=synthesis,
            all_citations=citations,
            word_count=word_count,
            llm_used=llm_used,
            created_at=datetime.now(timezone.utc),
            confidence_score=confidence,
        )

    def _extract_sections(self, content: str) -> list[IndustryPrimerSection]:
        headers = list(_SECTION_HEADER_RE.finditer(content))
        synthesis_match = _SYNTHESIS_HEADER_RE.search(content)
        end_of_last_section = synthesis_match.start() if synthesis_match else len(content)

        sections: list[IndustryPrimerSection] = []
        for i, header in enumerate(headers):
            body_start = header.end()
            body_end = headers[i + 1].start() if i + 1 < len(headers) else end_of_last_section
            body = content[body_start:body_end].strip()

            section_citations = [
                {"doc": d, "section": s, "quote": q} for d, s, q in CITATION_PATTERN.findall(body)
            ]
            sections.append(
                IndustryPrimerSection(
                    section_number=int(header.group(1)),
                    section_name=header.group(2).strip(),
                    content=body,
                    citations=section_citations,
                    word_count=len(body.split()),
                )
            )
        return sections

    def _extract_synthesis(self, content: str) -> list[InvestorSynthesisBullet]:
        synthesis_match = _SYNTHESIS_HEADER_RE.search(content)
        if synthesis_match is None:
            return []

        synthesis_body = content[synthesis_match.end():]
        bullets = _SYNTHESIS_BULLET_RE.findall(synthesis_body)

        result: list[InvestorSynthesisBullet] = []
        for i, bullet_text in enumerate(bullets):
            bullet_citations = [
                {"doc": d, "section": s, "quote": q}
                for d, s, q in CITATION_PATTERN.findall(bullet_text)
            ]
            topic = _SYNTHESIS_TOPICS[i] if i < len(_SYNTHESIS_TOPICS) else f"bullet_{i}"
            result.append(
                InvestorSynthesisBullet(
                    topic=topic,
                    content=bullet_text.strip(),
                    citations=bullet_citations,
                )
            )
        return result
