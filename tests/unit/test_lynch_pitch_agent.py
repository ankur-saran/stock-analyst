"""Unit tests for the Lynch Pitch agent.

Mirrors the mocking conventions in ``test_industry_analyst.py``: the LLM
call and tool functions are mocked at the module level they're imported into
(``agents.lynch_pitch.agent``), and ``_execute``'s private seams --
``_run_rag_searches``, ``_build_rag_context``, ``_build_user_message``, and
``_parse_pitch_output`` -- are exercised directly so tests don't depend on a
real LLM, database, or Qdrant instance.
"""
from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from rag.retrieval.hybrid_retriever import RetrievedChunk

import agents.lynch_pitch.agent as agent_module
from agents.lynch_pitch.agent import LynchPitchAgent, _RAG_QUERIES
from agents.lynch_pitch.schemas import CompanyType, LynchPitch
from agents.shared.message import AgentMessage, AgentType

TENANT_ID = str(uuid.uuid4())
COVERAGE_ID = str(uuid.uuid4())
COMPANY_INFO = {"company_name": "Acme Corp", "ticker": "ACME"}


def _q(num: int, heading: str, body: str) -> str:
    return f"### Q{num}: {heading}\n{body}\n"


_HEADINGS = {
    1: "What does this company do?",
    2: "What is the single reason this stock could work?",
    3: "How does the company make money?",
    4: "Balance sheet health",
    5: "What type of company is this?",
    6: "What could go wrong?",
    7: "Why might the market be mispricing this?",
    8: "Bottom line",
}

_BODIES = {
    1: (
        "Acme Corp sells industrial sensors to manufacturers "
        '[10-K FY2023, Item 1]: "the Company designs and sells industrial sensors to manufacturing customers" '
        "-> its core business is selling sensors to factories."
    ),
    2: (
        "Its sensors are becoming mandatory for automation compliance "
        '[10-K FY2023, Item 1]: "new automation regulations are expected to expand demand for the sensor products" '
        "-> regulatory tailwinds are a single durable growth driver."
    ),
    3: (
        "Acme earns high-margin recurring sensor and service revenue "
        '[10-K FY2023, Item 7]: "gross margin was 62 percent for fiscal 2023, up from 58 percent in fiscal 2022" '
        "-> margins are expanding as the mix shifts to services."
    ),
    4: (
        "The company carries modest leverage and strong liquidity "
        '[10-K FY2023, Item 8]: "total debt was 120 million and cash and equivalents were 340 million at fiscal year end" '
        "-> a net cash position gives room to invest."
    ),
    5: (
        "This is best described as a {company_type} "
        '[10-K FY2023, Item 7]: "revenue grew 28 percent year over year in fiscal 2023" '
        "-> consistent high growth supports this classification."
    ),
    6: (
        "Customer concentration and input cost inflation are real risks "
        '[10-K FY2023, Item 1A]: "the top five customers represented approximately 40 percent of total revenue" '
        "-> losing a large customer would hurt results."
    ),
    7: (
        "The market may be undervaluing the recurring nature of service revenue "
        '[10-K FY2023, Item 7]: "service revenue which recurs annually grew to 30 percent of total revenue" '
        "-> a growing recurring base deserves a higher multiple than the market assigns."
    ),
    8: (
        "Acme is interesting because regulation-driven demand and margin expansion are visible in its own filings "
        '[10-K FY2023, Item 7]: "management expects continued margin expansion as service mix increases" '
        "-> the bet is that this mix continues; if margins stall or a top customer leaves, the thesis breaks."
    ),
}


def _make_content(question_numbers: list[int], company_type: str = "fast grower") -> str:
    parts = []
    for n in question_numbers:
        body = _BODIES[n].format(company_type=company_type)
        parts.append(_q(n, _HEADINGS[n], body))
    return "\n".join(parts)


def _valid_pitch_content(company_type: str = "fast grower") -> str:
    return _make_content(list(range(1, 9)), company_type=company_type)


def _chunk(chunk_id: str, content: str = "some evidence text") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=chunk_id,
        content=content,
        metadata={"document_name": "10-K FY2023", "section_name": "Item 1"},
        score=0.9,
        parent_content=None,
        parent_chunk_id=None,
    )


@pytest.fixture()
def db_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def agent(db_session: AsyncMock) -> LynchPitchAgent:
    return LynchPitchAgent(db_session=db_session)


def _message(**payload_overrides) -> AgentMessage:
    return AgentMessage(
        sender=AgentType.ORCHESTRATOR,
        recipient=AgentType.LYNCH_PITCH,
        task_id=str(uuid.uuid4()),
        coverage_id=COVERAGE_ID,
        tenant_id=TENANT_ID,
        payload=payload_overrides,
    )


# ── 1. _build_rag_context deduplicates chunks ───────────────────────────────


def test_build_rag_context_deduplicates_chunks_by_chunk_id(agent: LynchPitchAgent) -> None:
    shared_chunk = _chunk("chunk-1", "shared passage")
    results = [
        [shared_chunk, _chunk("chunk-2", "second passage")],
        [shared_chunk],  # same chunk_id returned by a second query
        [],
        [],
        [],
        [],
    ]

    context = agent._build_rag_context(results, _RAG_QUERIES)

    assert context.count('"shared passage"') == 1
    assert context.count('"second passage"') == 1


# ── 2. _build_user_message includes company, context, financial summary ────


def test_build_user_message_includes_company_context_and_financials(
    agent: LynchPitchAgent,
) -> None:
    context = "EVIDENCE FOR 'revenue': [10-K, Item 7]: \"revenue grew\""
    fin_summary = {"revenue": {"value": 100.0, "unit": "USD_millions", "period": "FY2023"}}

    message = agent._build_user_message(COMPANY_INFO, context, fin_summary, None, None)

    assert COMPANY_INFO["company_name"] in message
    assert COMPANY_INFO["ticker"] in message
    assert context in message
    assert "100.0" in message


# ── 3. _build_user_message includes retry_prompt when provided ─────────────


def test_build_user_message_includes_retry_prompt_when_provided(agent: LynchPitchAgent) -> None:
    retry_prompt = "FAILED: citation_coverage -- Paragraph 3 has no citation"

    message = agent._build_user_message(COMPANY_INFO, "context", {}, None, retry_prompt)

    assert retry_prompt in message
    assert "PREVIOUS ATTEMPT FAILED VALIDATION" in message


def test_build_user_message_omits_retry_section_when_absent(agent: LynchPitchAgent) -> None:
    message = agent._build_user_message(COMPANY_INFO, "context", {}, None, None)

    assert "PREVIOUS ATTEMPT FAILED VALIDATION" not in message


# ── 4. _parse_pitch_output on valid 8-question output ───────────────────────


def test_parse_pitch_output_returns_valid_pitch(agent: LynchPitchAgent) -> None:
    content = _valid_pitch_content()

    pitch = agent._parse_pitch_output(content, COVERAGE_ID, COMPANY_INFO, "claude-sonnet-4-6")

    assert isinstance(pitch, LynchPitch)
    assert pitch.coverage_id == COVERAGE_ID
    assert pitch.company_name == COMPANY_INFO["company_name"]
    assert pitch.ticker == COMPANY_INFO["ticker"]
    assert len(pitch.answers) == 8
    assert pitch.all_citations
    assert pitch.citation_coverage_pct >= 0.90
    assert pitch.llm_used == "claude-sonnet-4-6"


# ── 5. _parse_pitch_output on output with <8 questions ──────────────────────


def test_parse_pitch_output_rejects_fewer_than_eight_questions(agent: LynchPitchAgent) -> None:
    content = _make_content([1, 2, 3, 4, 5])

    with pytest.raises(ValidationError):
        agent._parse_pitch_output(content, COVERAGE_ID, COMPANY_INFO, "claude-sonnet-4-6")


# ── 6. company_type extracted from Q5 ────────────────────────────────────────


def test_parse_pitch_output_extracts_company_type_from_q5(agent: LynchPitchAgent) -> None:
    content = _valid_pitch_content(company_type="fast grower")

    pitch = agent._parse_pitch_output(content, COVERAGE_ID, COMPANY_INFO, "claude-sonnet-4-6")

    assert pitch.company_type == CompanyType.FAST_GROWER


def test_parse_pitch_output_raises_when_company_type_undetectable(agent: LynchPitchAgent) -> None:
    content = _valid_pitch_content(company_type="a very promising business")

    with pytest.raises(ValueError):
        agent._parse_pitch_output(content, COVERAGE_ID, COMPANY_INFO, "claude-sonnet-4-6")


# ── 7. Full _execute flow with mocked LLM ────────────────────────────────────


async def test_execute_saves_output_and_returns_agent_output(
    agent: LynchPitchAgent, db_session: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_session.get = AsyncMock(
        return_value=SimpleNamespace(
            ticker=COMPANY_INFO["ticker"], company_name=COMPANY_INFO["company_name"]
        )
    )
    agent.retriever = SimpleNamespace(retrieve=AsyncMock(return_value=[]))

    monkeypatch.setattr(agent_module, "get_financial_summary", AsyncMock(return_value={}))
    monkeypatch.setattr(agent_module, "get_management_credibility_score", AsyncMock(return_value=None))
    mock_save = AsyncMock(return_value=str(uuid.uuid4()))
    monkeypatch.setattr(agent_module, "save_bull_case", mock_save)
    monkeypatch.setattr(
        LynchPitchAgent,
        "_call_llm",
        AsyncMock(return_value=(_valid_pitch_content(), "claude-sonnet-4-6", 4321)),
    )

    output = await agent._execute(_message())

    mock_save.assert_awaited_once()
    assert output.agent == AgentType.LYNCH_PITCH
    assert output.coverage_id == COVERAGE_ID
    assert output.tenant_id == TENANT_ID
    assert output.llm_used == "claude-sonnet-4-6"
    assert output.tokens_used == 4321
    assert output.citations
    assert output.message_id == mock_save.return_value


# ── 8. RAG searches run in parallel via asyncio.gather ──────────────────────


async def test_rag_searches_run_concurrently_via_gather(
    agent: LynchPitchAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_retrieve = AsyncMock(return_value=[])
    agent.retriever = SimpleNamespace(retrieve=mock_retrieve)

    real_gather = agent_module.asyncio.gather

    async def _gather_side_effect(*aws: object, **kw: object) -> object:
        return await real_gather(*aws, **kw)

    mock_gather = AsyncMock(side_effect=_gather_side_effect)
    monkeypatch.setattr(agent_module.asyncio, "gather", mock_gather)

    results = await agent._run_rag_searches(TENANT_ID, COVERAGE_ID)

    mock_gather.assert_awaited_once()
    assert len(mock_gather.call_args.args) == len(_RAG_QUERIES)
    assert mock_retrieve.call_count == len(_RAG_QUERIES)
    assert results == [[] for _ in _RAG_QUERIES]
