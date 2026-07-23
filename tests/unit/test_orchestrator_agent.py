"""Unit tests for the Orchestrator agent.

The Orchestrator's own logic is thin by design — it delegates prerequisite
checks to ``agents.orchestrator.tools`` and planning to the LLM — so every
test here mocks those two seams (the tool functions and ``_call_llm``) and
asserts on how ``OrchestratorAgent`` reacts to what they return, per the
"Mock the tool functions and LLM call" brief. The one exception is the
dispatch test, which lets the real ``dispatch_task`` run against a mocked DB
session so the agent-name plumbing into ``run_agent_task.delay`` is verified
end-to-end.
"""
from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

import agents.orchestrator.agent as agent_module
import agents.orchestrator.tools as tools_module
from agents.orchestrator.agent import OrchestratorAgent
from agents.shared.message import AgentMessage, AgentType

TENANT_ID = str(uuid.uuid4())
COVERAGE_ID = str(uuid.uuid4())

_FULL_FILING_STATUS = {
    "count": 3,
    "years_covered": ["2021", "2022", "2023"],
    "meets_minimum": True,
}


def _message(user_request: str) -> AgentMessage:
    return AgentMessage(
        sender=AgentType.ORCHESTRATOR,
        recipient=AgentType.ORCHESTRATOR,
        task_id=str(uuid.uuid4()),
        coverage_id=COVERAGE_ID,
        tenant_id=TENANT_ID,
        payload={"user_request": user_request},
    )


def _mock_prereqs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    coverage_exists: bool = True,
    industry_loaded: bool = True,
    filing_status: dict | None = None,
) -> None:
    monkeypatch.setattr(
        agent_module, "check_coverage_exists", AsyncMock(return_value=coverage_exists)
    )
    monkeypatch.setattr(
        agent_module, "check_industry_loaded", AsyncMock(return_value=industry_loaded)
    )
    monkeypatch.setattr(
        agent_module,
        "check_filing_count",
        AsyncMock(return_value=filing_status if filing_status is not None else _FULL_FILING_STATUS),
    )


def _mock_llm(monkeypatch: pytest.MonkeyPatch, content: str) -> AsyncMock:
    mock = AsyncMock(return_value=(content, "gpt-4o", 123))
    monkeypatch.setattr(OrchestratorAgent, "_call_llm", mock)
    return mock


def _plan_json(**overrides) -> str:
    plan = {
        "plan_id": str(uuid.uuid4()),
        "intent_detected": "unspecified",
        "steps": [],
        "estimated_duration_seconds": 0,
        "prerequisites_met": True,
        "missing_prerequisites": [],
        "routing_confidence": 0.9,
    }
    plan.update(overrides)
    return json.dumps(plan)


@pytest.fixture()
def db_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def orchestrator(db_session: AsyncMock) -> OrchestratorAgent:
    return OrchestratorAgent(db_session=db_session)


# ── 1-2. Happy path routing ──────────────────────────────────────────────────


async def test_bull_case_routes_to_lynch_pitch(
    orchestrator: OrchestratorAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_prereqs(monkeypatch)
    _mock_llm(
        monkeypatch,
        _plan_json(
            intent_detected="bull_case",
            steps=[{"step": 1, "agent": "lynch_pitch", "skill": "generate_pitch", "input": {}}],
        ),
    )
    monkeypatch.setattr(agent_module, "dispatch_task", AsyncMock(return_value="task-1"))

    output = await orchestrator._execute(_message("Run a bull case for AAPL"))
    plan = json.loads(output.content)

    assert plan["steps"][0]["agent"] == "lynch_pitch"
    assert plan["prerequisites_met"] is True


async def test_bear_case_routes_to_munger_invert(
    orchestrator: OrchestratorAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_prereqs(monkeypatch)
    _mock_llm(
        monkeypatch,
        _plan_json(
            intent_detected="bear_case",
            steps=[{"step": 1, "agent": "munger_invert", "skill": "invert", "input": {}}],
        ),
    )
    monkeypatch.setattr(agent_module, "dispatch_task", AsyncMock(return_value="task-1"))

    output = await orchestrator._execute(_message("Give me the bear case / Munger invert"))
    plan = json.loads(output.content)

    assert plan["steps"][0]["agent"] == "munger_invert"


# ── 3-4. Missing prerequisites ───────────────────────────────────────────────


async def test_missing_industry_blocks_with_reason(
    orchestrator: OrchestratorAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_prereqs(monkeypatch, industry_loaded=False)
    _mock_llm(
        monkeypatch,
        _plan_json(
            prerequisites_met=False,
            missing_prerequisites=["industry fundamentals have not been loaded for this coverage"],
            routing_confidence=1.0,
        ),
    )

    output = await orchestrator._execute(_message("Run a bull case for AAPL"))
    plan = json.loads(output.content)

    assert plan["prerequisites_met"] is False
    assert any("industry" in item.lower() for item in plan["missing_prerequisites"])


async def test_insufficient_filings_blocks_with_reason(
    orchestrator: OrchestratorAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_prereqs(
        monkeypatch,
        filing_status={"count": 1, "years_covered": ["2023"], "meets_minimum": False},
    )
    _mock_llm(
        monkeypatch,
        _plan_json(
            prerequisites_met=False,
            missing_prerequisites=["at least 3 years of annual 10-K filings are required"],
            routing_confidence=1.0,
        ),
    )

    output = await orchestrator._execute(_message("Run a bull case for AAPL"))
    plan = json.loads(output.content)

    assert plan["prerequisites_met"] is False
    assert any("filing" in item.lower() for item in plan["missing_prerequisites"])


# ── 5-6. JSON parsing robustness ─────────────────────────────────────────────


async def test_malformed_llm_json_raises_value_error(
    orchestrator: OrchestratorAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_prereqs(monkeypatch)
    _mock_llm(monkeypatch, "Sure! I can't format that as JSON right now, sorry about that.")

    with pytest.raises(ValueError):
        await orchestrator._execute(_message("Run a bull case for AAPL"))


async def test_markdown_fenced_json_is_extracted(
    orchestrator: OrchestratorAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_prereqs(monkeypatch)
    fenced = "Here you go:\n```json\n" + _plan_json(
        steps=[{"step": 1, "agent": "lynch_pitch", "skill": "generate_pitch", "input": {}}],
    ) + "\n```"
    _mock_llm(monkeypatch, fenced)
    monkeypatch.setattr(agent_module, "dispatch_task", AsyncMock(return_value="task-1"))

    output = await orchestrator._execute(_message("Run a bull case for AAPL"))
    plan = json.loads(output.content)

    assert plan["steps"][0]["agent"] == "lynch_pitch"


# ── 7. Dispatch plumbing ─────────────────────────────────────────────────────


async def test_dispatch_calls_run_agent_task_with_correct_agent(
    orchestrator: OrchestratorAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    _mock_prereqs(monkeypatch)
    _mock_llm(
        monkeypatch,
        _plan_json(
            steps=[{"step": 1, "agent": "lynch_pitch", "skill": "generate_pitch", "input": {}}],
        ),
    )

    # run_agent_task.delay() is a plain sync Celery call (never awaited by
    # dispatch_task), so it's mocked with MagicMock, not AsyncMock — an
    # AsyncMock here would hand dispatch_task an unawaited coroutine instead
    # of an AsyncResult-like object, and `.celery_task_id = async_result.id`
    # would blow up.
    mock_delay = MagicMock(return_value=MagicMock(id="celery-task-1"))
    monkeypatch.setattr(tools_module.run_agent_task, "delay", mock_delay)

    await orchestrator._execute(_message("Run a bull case for AAPL"))

    mock_delay.assert_called_once()
    called_agent = mock_delay.call_args.args[1]
    assert called_agent == "lynch_pitch"
