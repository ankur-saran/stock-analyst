"""The Orchestrator: plans, routes, and monitors — never generates research.

Every user request enters the platform through here first. It checks
prerequisites (coverage exists, industry loaded, enough annual filings),
asks the LLM to turn the request into a routing plan, and — if prerequisites
are met — dispatches the first step to a specialist agent via
``agents.orchestrator.tools.dispatch_task``. It always returns structured
JSON and, unlike every other agent, skips the Citation Enforcer entirely:
a routing plan makes no factual claims to cite.
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

from agents.shared.base_agent import BaseAgent
from agents.shared.message import AgentMessage, AgentOutput, AgentType, LLMTier
from agents.orchestrator.tools import (
    check_coverage_exists,
    check_filing_count,
    check_industry_loaded,
    dispatch_task,
)

ORCHESTRATOR_SYSTEM_PROMPT = """
You are the Orchestrator for a professional equity research platform.
Your ONLY job is to plan, route, and monitor — never generate research yourself.

ROUTING RULES:
- "industry overview", "industry analysis", "what industry is this" -> industry_analyst
- "fetch filings", "upload document", "get 10-K" -> document_ingestion
- "why own", "bull case", "Lynch pitch", "why invest" -> lynch_pitch
- "why not own", "bear case", "Munger invert", "risks", "how could I lose" -> munger_invert
- "earnings", "quarterly update", "new 10-Q", "guidance vs results" -> earnings_monitor
- "KPIs", "metrics", "revenue trend", "time series" -> kpi_tracker

The "agent" field in every step MUST be one of the exact strings above
(industry_analyst, document_ingestion, lynch_pitch, munger_invert,
earnings_monitor, kpi_tracker) — never a class name, never invented.

PLANNING RULES:
1. Always check if the coverage (stock project) exists before routing.
2. Always check if industry fundamentals are loaded before allowing research agents.
3. Always check if minimum 3 years of annual filings are present before Bull/Bear cases.
4. If ANY prerequisite is missing: return PREREQUISITE_MISSING with exact instructions.

OUTPUT FORMAT — always return valid JSON, nothing else:
{
  "plan_id": "<uuid>",
  "intent_detected": "<what the user wants>",
  "steps": [
    {"step": 1, "agent": "<agent_type>", "skill": "<skill_name>", "input": {}}
  ],
  "estimated_duration_seconds": <int>,
  "prerequisites_met": <bool>,
  "missing_prerequisites": ["<description of what's missing>"],
  "routing_confidence": <float 0-1>
}

If prerequisites are NOT met, return:
{
  "plan_id": "<uuid>",
  "intent_detected": "<what the user wants>",
  "steps": [],
  "estimated_duration_seconds": 0,
  "prerequisites_met": false,
  "missing_prerequisites": ["<specific missing item>"],
  "routing_confidence": 1.0
}
"""

_REPAIR_INSTRUCTION = (
    "Your previous response was not valid JSON matching the required schema. "
    "Return ONLY the JSON object described in the system prompt — no prose, "
    "no markdown code fences, no explanation."
)

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BRACE_RE = re.compile(r"\{.*\}", re.DOTALL)


class OrchestratorAgent(BaseAgent):
    agent_type = AgentType.ORCHESTRATOR

    async def _execute(self, message: AgentMessage) -> AgentOutput:
        prereqs = await self._check_prerequisites(message)

        messages = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "user_request": message.payload.get("user_request", ""),
                        "coverage_id": message.coverage_id,
                        "prerequisites_status": prereqs,
                    }
                ),
            },
        ]

        plan, model_used, tokens = await self._plan_with_retry(messages)

        dispatched_task_id = None
        if plan.get("prerequisites_met") and plan.get("steps"):
            first_step = plan["steps"][0]
            dispatched_task_id = await dispatch_task(
                agent=first_step["agent"],
                skill=first_step["skill"],
                payload={**first_step.get("input", {}), "original_request": message.payload},
                coverage_id=message.coverage_id,
                tenant_id=message.tenant_id,
                db=self.db,
            )
            plan["dispatched_task_id"] = dispatched_task_id

        return AgentOutput(
            message_id=str(uuid.uuid4()),
            agent=AgentType.ORCHESTRATOR,
            task_id=message.task_id,
            coverage_id=message.coverage_id,
            tenant_id=message.tenant_id,
            content=json.dumps(plan, indent=2),
            citations=[],
            citation_coverage_pct=1.0,
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,  # overwritten by BaseAgent.run() once _execute returns
            approved_by_enforcer=True,  # plans aren't research claims — no enforcer pass
            enforcer_status="approved",
        )

    async def _check_prerequisites(self, message: AgentMessage) -> dict[str, Any]:
        coverage_id = message.coverage_id
        tenant_id = message.tenant_id

        exists = await check_coverage_exists(coverage_id, tenant_id, self.db)
        industry_loaded = await check_industry_loaded(coverage_id, self.db) if exists else False
        filing_status = (
            await check_filing_count(coverage_id, "10-K", 3, self.db) if exists else {}
        )

        return {
            "coverage_exists": exists,
            "industry_loaded": industry_loaded,
            "annual_filings": filing_status.get("count", 0),
            "annual_filings_years": filing_status.get("years_covered", []),
            "min_filings_met": filing_status.get("meets_minimum", False),
        }

    async def _plan_with_retry(
        self, messages: list[dict[str, str]]
    ) -> tuple[dict[str, Any], str, int]:
        """Call the LLM, and if it doesn't return parseable JSON, retry once
        with an explicit repair instruction before giving up.

        Returns ``(plan, model_used, total_tokens_across_both_calls)``.
        """
        content, model_used, tokens = await self._call_llm(
            messages=messages, tier=LLMTier.SECONDARY, max_tokens=1024
        )
        plan = self._parse_plan(content)
        if plan is not None:
            return plan, model_used, tokens

        repair_messages = [
            *messages,
            {"role": "assistant", "content": content},
            {"role": "user", "content": _REPAIR_INSTRUCTION},
        ]
        retry_content, retry_model, retry_tokens = await self._call_llm(
            messages=repair_messages, tier=LLMTier.SECONDARY, max_tokens=1024
        )
        plan = self._parse_plan(retry_content)
        if plan is not None:
            return plan, retry_model, tokens + retry_tokens

        raise ValueError(
            f"Orchestrator returned non-JSON response after repair attempt: {retry_content[:200]}"
        )

    @staticmethod
    def _parse_plan(content: str) -> dict[str, Any] | None:
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        fence_match = _JSON_FENCE_RE.search(content)
        if fence_match:
            try:
                return json.loads(fence_match.group(1))
            except json.JSONDecodeError:
                pass

        brace_match = _BRACE_RE.search(content)
        if brace_match:
            try:
                return json.loads(brace_match.group())
            except json.JSONDecodeError:
                pass

        return None
