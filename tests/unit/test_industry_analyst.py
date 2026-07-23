"""Unit tests for the Industry Analyst agent.

Mirrors the mocking conventions in ``test_orchestrator_agent.py``: the LLM
call and tool functions are mocked at the module level they're imported
into (``agents.industry_analyst.agent``), and ``_execute``'s two private
seams — ``_gather_research``/``_build_user_message`` and
``_parse_primer_output`` — are exercised directly so tests don't depend on
a real LLM or network access.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import SecretStr, ValidationError

import agents.industry_analyst.agent as agent_module
import agents.industry_analyst.tools as tools_module
from agents.industry_analyst.agent import IndustryAnalystAgent
from agents.industry_analyst.schemas import IndustryPrimer

INDUSTRY_ID = str(uuid.uuid4())
INDUSTRY_NAME = "Enterprise Software"

_SECTION_NAMES = [
    "Industry Purpose & Core Economics",
    "Industry Structure & Competitive Shape",
    "Demand & Growth Drivers",
    "Supply Side, Cost Structure & Constraints",
    "Technology, Regulation & Structural Change",
    "Medium-Term Outlook (5-10 Years)",
]

_SYNTHESIS_BULLETS = [
    '- Core economic engine relies on recurring subscription revenue '
    '[Source 1, Report]: "recurring revenue drives durable operating margins over time"',
    '- Primary growth lever is expansion into adjacent international markets '
    '[Source 2, Report]: "expansion into new geographic markets accelerated overall growth"',
    '- Structural constraint investors underestimate is customer concentration '
    '[Source 3, Report]: "the top ten customers represent a large share of total revenue"',
    '- Key risk is a shift in the regulatory posture toward the sector '
    '[Source 4, Report]: "regulators signaled new interest in oversight of this sector"',
    '- Companies that win combine product scale with high switching costs '
    '[Source 5, Report]: "scale combined with lock-in produces a durable competitive advantage"',
]


def _make_content(section_names: list[str], body_words_per_section: int) -> str:
    parts = []
    for i, name in enumerate(section_names, start=1):
        filler = " ".join(["industry"] * body_words_per_section)
        parts.append(
            f"## {i}. {name}\n\n"
            f'{filler} [Source {i}, Report]: "this is a sufficiently long exact quote for citation number {i}"\n'
        )
    parts.append("## Investor Synthesis\n\n" + "\n".join(_SYNTHESIS_BULLETS))
    return "\n".join(parts)


def _valid_primer_content() -> str:
    return _make_content(_SECTION_NAMES, body_words_per_section=210)


@pytest.fixture()
def db_session() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def agent(db_session: AsyncMock) -> IndustryAnalystAgent:
    return IndustryAnalystAgent(db_session=db_session)


# ── 1. _gather_research ──────────────────────────────────────────────────────


async def test_gather_research_makes_exactly_three_web_searches(
    agent: IndustryAnalystAgent, monkeypatch: pytest.MonkeyPatch
) -> None:
    mock_search = AsyncMock(
        return_value=[
            {"title": "Industry Report", "url": "https://example.com/a", "published_date": "2024-01-01", "content": "some content"}
        ]
    )
    monkeypatch.setattr(agent_module, "web_search", mock_search)

    await agent._gather_research(INDUSTRY_NAME, INDUSTRY_ID)

    assert mock_search.call_count == 3


# ── 2. _build_user_message ───────────────────────────────────────────────────


def test_build_user_message_includes_name_and_research_context(agent: IndustryAnalystAgent) -> None:
    research_context = "=== WEB RESEARCH CONTEXT ===\nSOURCE: [Example, https://example.com, 2024]\nCONTENT: some evidence"

    message = agent._build_user_message(INDUSTRY_NAME, research_context)

    assert INDUSTRY_NAME in message
    assert research_context in message


# ── 3. _parse_primer_output — valid structure ───────────────────────────────


def test_parse_primer_output_returns_valid_primer(agent: IndustryAnalystAgent) -> None:
    content = _valid_primer_content()

    primer = agent._parse_primer_output(content, INDUSTRY_ID, INDUSTRY_NAME, "claude-sonnet-4-6")

    assert isinstance(primer, IndustryPrimer)
    assert primer.industry_id == INDUSTRY_ID
    assert primer.industry_name == INDUSTRY_NAME
    assert len(primer.sections) == 6
    assert len(primer.investor_synthesis) == 5
    assert primer.all_citations
    assert primer.llm_used == "claude-sonnet-4-6"
    assert 0.0 <= primer.confidence_score <= 1.0


# ── 4. _parse_primer_output — too few sections ──────────────────────────────


def test_parse_primer_output_rejects_fewer_than_six_sections(agent: IndustryAnalystAgent) -> None:
    content = _make_content(_SECTION_NAMES[:5], body_words_per_section=210)

    with pytest.raises(ValidationError):
        agent._parse_primer_output(content, INDUSTRY_ID, INDUSTRY_NAME, "claude-sonnet-4-6")


# ── 5. _parse_primer_output — word count too low ────────────────────────────


def test_parse_primer_output_rejects_word_count_below_minimum(agent: IndustryAnalystAgent) -> None:
    content = _make_content(_SECTION_NAMES, body_words_per_section=5)

    with pytest.raises(ValidationError):
        agent._parse_primer_output(content, INDUSTRY_ID, INDUSTRY_NAME, "claude-sonnet-4-6")


# ── 6-7. fetch_url domain allowlist ──────────────────────────────────────────


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=None, response=None)  # type: ignore[arg-type]


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse | None = None, exception: Exception | None = None) -> None:
        self._response = response
        self._exception = exception

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> bool:
        return False

    async def get(self, url: str, *args: object, **kwargs: object) -> _FakeResponse:
        if self._exception:
            raise self._exception
        assert self._response is not None
        return self._response

    async def post(self, url: str, *args: object, **kwargs: object) -> _FakeResponse:
        if self._exception:
            raise self._exception
        assert self._response is not None
        return self._response


async def test_fetch_url_allowed_domain_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    html = "<html><body><p>SEC filings disclose annual revenue figures.</p></body></html>"
    monkeypatch.setattr(
        tools_module.httpx, "AsyncClient", lambda **kwargs: _FakeAsyncClient(response=_FakeResponse(html))
    )

    result = await tools_module.fetch_url("https://www.sec.gov/some/filing.htm")

    assert "SEC filings disclose annual revenue figures." in result


async def test_fetch_url_disallowed_domain_raises_value_error() -> None:
    with pytest.raises(ValueError):
        await tools_module.fetch_url("https://malicious-example.com/x")


# ── 8. web_search timeout propagates ─────────────────────────────────────────


async def test_web_search_timeout_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tools_module.settings, "tavily_api_key", SecretStr("tvly-real-key"))
    monkeypatch.setattr(
        tools_module.httpx,
        "AsyncClient",
        lambda **kwargs: _FakeAsyncClient(exception=httpx.TimeoutException("timed out")),
    )

    with pytest.raises(httpx.TimeoutException):
        await tools_module.web_search("Enterprise Software industry economics")
