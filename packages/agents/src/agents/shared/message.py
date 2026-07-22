"""Shared inter-agent message envelope.

Every agent-to-agent call goes through :class:`AgentMessage` on the way in
and :class:`AgentOutput` on the way out, so the LangGraph orchestrator,
Celery dispatch, and the audit log all speak one schema regardless of which
of the 7 agents is involved.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    INDUSTRY_ANALYST = "industry_analyst"
    DOCUMENT_INGESTION = "document_ingestion"
    LYNCH_PITCH = "lynch_pitch"
    MUNGER_INVERT = "munger_invert"
    EARNINGS_MONITOR = "earnings_monitor"
    KPI_TRACKER = "kpi_tracker"
    CITATION_ENFORCER = "citation_enforcer"


class LLMTier(str, Enum):
    PRIMARY = "primary"  # Claude — complex reasoning
    SECONDARY = "secondary"  # GPT-4o — structured extraction
    LOCAL = "local"  # Llama 3.1 — air-gapped / cost control


class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: AgentType
    recipient: AgentType
    task_id: str
    coverage_id: str
    tenant_id: str
    payload: dict[str, Any]
    requires_citation: bool = True
    llm_preference: LLMTier = LLMTier.PRIMARY
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    parent_message_id: str | None = None


class AgentOutput(BaseModel):
    message_id: str
    agent: AgentType
    task_id: str
    coverage_id: str
    tenant_id: str
    content: str  # Markdown with inline citations
    citations: list[dict[str, Any]]  # list of Citation dicts
    citation_coverage_pct: float
    llm_used: str
    tokens_used: int
    latency_ms: int
    approved_by_enforcer: bool = False
    enforcer_status: str = "pending"  # pending / approved / partial / failed
    error: str | None = None
