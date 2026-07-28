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
from shared.streaming import StreamingService
from sqlalchemy.ext.asyncio import AsyncSession

from agents.shared.citation_enforcer import CITATION_PATTERN
from agents.shared.message import AgentMessage, AgentOutput, AgentType, LLMTier

settings = Settings()

# Emit a chunk once the buffer reaches this size...
_CHUNK_FLUSH_THRESHOLD = 100
# ...but force a flush past this size even if a citation never resolves, so
# malformed/unbounded output can't stall streaming indefinitely.
_CHUNK_FORCE_FLUSH_THRESHOLD = 2000


class BaseAgent(ABC):
    agent_type: AgentType  # must be set by subclass

    def __init__(
        self,
        db_session: AsyncSession,
        retriever: HybridRetriever | None = None,
        streaming_svc: StreamingService | None = None,
        task_id: str | None = None,
    ) -> None:
        self.db = db_session
        self.retriever = retriever
        self.litellm_base_url = settings.litellm_url
        self.streaming_svc = streaming_svc
        self.task_id = task_id

    async def _emit(self, event: dict[str, Any]) -> None:
        """Publish a streaming event, if streaming is configured for this run.

        No-ops silently when either half of the pair is missing (e.g. every
        call site that doesn't pass ``streaming_svc``/``task_id`` today) so
        streaming stays entirely opt-in.
        """
        if self.streaming_svc is None or self.task_id is None:
            return
        await self.streaming_svc.publish_event(self.task_id, event)

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

        if self.streaming_svc is not None and self.task_id is not None:
            return await self._call_llm_streaming(kwargs)

        response = await litellm.acompletion(**kwargs)
        content: str = response.choices[0].message.content
        model_used: str = response.model
        tokens: int = response.usage.total_tokens
        return content, model_used, tokens

    async def _call_llm_streaming(self, kwargs: dict[str, Any]) -> tuple[str, str, int]:
        """Stream the completion, publishing citation-safe ``chunk``/``citation_found``
        events as tokens arrive, then reconstruct the full response for the return value.

        ``litellm.stream_chunk_builder`` is litellm's own utility for turning a
        list of streamed chunks back into one response object (content, model,
        usage) -- used here instead of hand-parsing so token accounting stays
        correct regardless of provider.
        """
        kwargs = {**kwargs, "stream": True, "stream_options": {"include_usage": True}}
        chunks: list[Any] = []
        buffer = ""
        seen_citations: set[tuple[str, str, str]] = set()

        stream = await litellm.acompletion(**kwargs)
        async for piece in stream:
            chunks.append(piece)
            delta = piece.choices[0].delta.content if piece.choices else None
            if not delta:
                continue
            buffer += delta
            if len(buffer) >= _CHUNK_FLUSH_THRESHOLD:
                buffer = await self._flush_chunk(buffer, seen_citations, force=False)

        if buffer:
            await self._flush_chunk(buffer, seen_citations, force=True)

        final = litellm.stream_chunk_builder(chunks, messages=kwargs["messages"])
        content: str = final.choices[0].message.content
        model_used: str = final.model
        tokens: int = final.usage.total_tokens
        return content, model_used, tokens

    async def _flush_chunk(
        self, buffer: str, seen_citations: set[tuple[str, str, str]], *, force: bool
    ) -> str:
        """Emit as much of ``buffer`` as is safe to send, returning the unflushed remainder.

        Never splits a citation across two events: if the buffer's trailing
        ``[`` isn't the start of a *complete* citation match, everything from
        that ``[`` onward is held back for the next flush -- unless ``force``
        (stream end, or the buffer has grown past the runaway cap), in which
        case the whole thing goes out as-is.
        """
        flush_to = len(buffer)
        if not force and len(buffer) < _CHUNK_FORCE_FLUSH_THRESHOLD:
            last_open = buffer.rfind("[")
            if last_open != -1:
                trailing = buffer[last_open:]
                if not CITATION_PATTERN.match(trailing):
                    flush_to = last_open

        if flush_to == 0:
            return buffer  # nothing safe to send yet

        flushed, remainder = buffer[:flush_to], buffer[flush_to:]
        citations = []
        for doc, section, quote in CITATION_PATTERN.findall(flushed):
            citation = {"doc": doc.strip(), "section": section.strip(), "quote": quote.strip()}
            key = (citation["doc"], citation["section"], citation["quote"])
            citations.append(citation)
            if key not in seen_citations:
                seen_citations.add(key)
                await self._emit({"type": "citation_found", **citation})

        await self._emit({"type": "chunk", "content": flushed, "citations": citations})
        return remainder

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
