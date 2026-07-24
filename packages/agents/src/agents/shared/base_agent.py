"""Abstract base class every agent inherits from.

Handles the three things that must be identical across all 7 agents: LLM
routing through the LiteLLM proxy, append-only audit logging to
``agent_audit_log``, and wrapping ``_execute`` so a failure is always logged
before it propagates.
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from abc import ABC, abstractmethod
from typing import Any

import litellm
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.config import Settings
from shared.models import AgentAuditLog
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shared.message import AgentMessage, AgentOutput, AgentType, LLMTier

settings = Settings()


class BaseAgent(ABC):
    agent_type: AgentType  # must be set by subclass

    def __init__(
        self, db_session: AsyncSession, retriever: HybridRetriever | None = None
    ) -> None:
        self.db = db_session
        self.retriever = retriever
        self.litellm_base_url = settings.litellm_url

    async def run(self, message: AgentMessage) -> AgentOutput:
        start = time.monotonic()
        try:
            result = await self._execute(message)
            result.latency_ms = int((time.monotonic() - start) * 1000)
            await self._log_audit(message, result, "success")
            return result
        except Exception as exc:
            await self._log_audit(message, None, "error", str(exc))
            raise

    @abstractmethod
    async def _execute(self, message: AgentMessage) -> AgentOutput:
        """Subclasses implement actual agent logic here."""

    async def _call_llm(
        self,
        messages: list[dict[str, str]],
        tier: LLMTier,
        max_tokens: int = 4096,
        extended_thinking: bool = False,
        response_format: dict[str, Any] | None = None,
    ) -> tuple[str, str, int]:
        """Call the LiteLLM proxy for the given tier.

        Returns ``(content, model_name, total_tokens)``. Exceptions from
        ``litellm.acompletion`` are intentionally not caught here — ``run()``
        is the single place that logs and re-raises failures.
        """
        model_name = tier.value  # "primary", "secondary", or "local" — matches config.yaml

        kwargs: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "base_url": self.litellm_base_url,
        }

        if extended_thinking and tier == LLMTier.PRIMARY:
            # Adaptive thinking — the fixed-budget_tokens form is deprecated/rejected
            # on current Claude models; let Claude decide how much to think.
            kwargs["thinking"] = {"type": "adaptive"}

        if response_format is not None:
            # Structured-extraction agents (e.g. KPI Tracker on GPT-4o) request
            # JSON-mode output; reasoning agents never pass this.
            kwargs["response_format"] = response_format

        response = await litellm.acompletion(**kwargs)
        content: str = response.choices[0].message.content
        model_used: str = response.model
        tokens: int = response.usage.total_tokens
        return content, model_used, tokens

    async def _log_audit(
        self,
        message: AgentMessage,
        result: AgentOutput | None,
        status: str,
        error: str | None = None,
    ) -> None:
        """Append-only INSERT into agent_audit_log via the ORM (parameterized)."""
        input_hash = hashlib.sha256(
            json.dumps(message.payload, sort_keys=True).encode()
        ).hexdigest()

        self.db.add(
            AgentAuditLog(
                tenant_id=uuid.UUID(message.tenant_id),
                coverage_id=uuid.UUID(message.coverage_id),
                agent_name=self.agent_type.value,
                action=status,
                input_hash=input_hash,
                output_id=uuid.UUID(result.message_id) if result else None,
                llm_used=result.llm_used if result else None,
                tokens_used=result.tokens_used if result else 0,
                latency_ms=result.latency_ms if result else None,
                log_metadata={"error": error} if error else {},
            )
        )
        await self.db.commit()
