"""Unit tests for the Citation Enforcer validation gate.

CitationEnforcer never calls an LLM — it runs six independent regex/RAG
checks against an AgentOutput's markdown content. Every check is exercised
both directly (fast, precise) and through the full ``validate()`` flow for
the hallucination / approved / rejected acceptance scenarios, since those
require the async retriever call and the assembled ValidationResult.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from agents.shared.citation_enforcer import CitationEnforcer
from agents.shared.message import AgentOutput, AgentType

TENANT_ID = "tenant-a"
COVERAGE_ID = "coverage-123"


def _make_output(content: str) -> AgentOutput:
    return AgentOutput(
        message_id="msg-1",
        agent=AgentType.LYNCH_PITCH,
        task_id="task-1",
        coverage_id=COVERAGE_ID,
        tenant_id=TENANT_ID,
        content=content,
        citations=[],
        citation_coverage_pct=0.0,
        llm_used="primary",
        tokens_used=100,
        latency_ms=10,
    )


@pytest.fixture()
def mock_retriever() -> AsyncMock:
    return AsyncMock()


@pytest.fixture()
def enforcer(mock_retriever: AsyncMock) -> CitationEnforcer:
    return CitationEnforcer(retriever=mock_retriever)


# ── 1-3. check_citation_coverage ─────────────────────────────────────────────


def test_coverage_all_paragraphs_cited_passes(enforcer: CitationEnforcer) -> None:
    content = (
        'Revenue was $383.3 billion in fiscal 2023. '
        '[AAPL 10-K 2023, Business]: "Revenue was $383.3 billion"\n\n'
        'Net income was $97 billion for the year. '
        '[AAPL 10-K 2023, Financials]: "Net income was $97 billion for fiscal 2023"'
    )
    result = enforcer._check_citation_coverage(content)
    assert result.passed is True


def test_coverage_80_percent_cited_fails(enforcer: CitationEnforcer) -> None:
    cited = (
        'Metric {i} was ${i}00 million in fiscal 2023. '
        '[AAPL 10-K 2023, Financials]: "Metric {i} was ${i}00 million for fiscal 2023"'
    )
    paragraphs = [cited.format(i=i) for i in range(1, 5)]  # 4 cited
    paragraphs.append("Metric 5 was $500 million in fiscal 2023.")  # 1 uncited
    content = "\n\n".join(paragraphs)

    result = enforcer._check_citation_coverage(content)
    assert result.passed is False
    assert "80.0%" in result.details
    assert len(result.failed_items) == 1


def test_coverage_no_claims_passes_vacuously(enforcer: CitationEnforcer) -> None:
    content = "# Overview\n\nApple Inc designs consumer electronics and services."
    result = enforcer._check_citation_coverage(content)
    assert result.passed is True


# ── 4-6. check_quote_format ──────────────────────────────────────────────────


def test_format_well_formed_citation_passes(enforcer: CitationEnforcer) -> None:
    content = '[AAPL 10-K 2023, Business]: "Revenue was $383.3 billion"'
    result = enforcer._check_quote_format(content)
    assert result.passed is True


def test_format_missing_section_fails(enforcer: CitationEnforcer) -> None:
    content = '[AAPL 10-K 2023]: "Revenue was $383.3 billion"'
    result = enforcer._check_quote_format(content)
    assert result.passed is False
    assert len(result.failed_items) == 1


def test_format_no_brackets_fails(enforcer: CitationEnforcer) -> None:
    content = 'AAPL 10-K 2023: "Revenue was $383.3 billion"'
    result = enforcer._check_quote_format(content)
    assert result.passed is False
    assert len(result.failed_items) == 1


# ── 7-9. check_quotes_exist_in_rag ────────────────────────────────────────────


async def test_quote_found_in_rag_passes(
    enforcer: CitationEnforcer, mock_retriever: AsyncMock
) -> None:
    mock_retriever.retrieve_exact_quote.return_value = object()  # any non-None chunk
    content = '[AAPL 10-K 2023, Business]: "Revenue was $383.3 billion in fiscal 2023"'

    result = await enforcer._check_quotes_exist_in_rag(content, TENANT_ID, COVERAGE_ID)
    assert result.passed is True
    assert result.failed_items == []


async def test_quote_not_found_in_rag_fails(
    enforcer: CitationEnforcer, mock_retriever: AsyncMock
) -> None:
    mock_retriever.retrieve_exact_quote.return_value = None
    content = '[AAPL 10-K 2023, Business]: "Revenue was $383.3 billion in fiscal 2023"'

    result = await enforcer._check_quotes_exist_in_rag(content, TENANT_ID, COVERAGE_ID)
    assert result.passed is False
    assert len(result.failed_items) == 1
    assert "Revenue was $383.3 billion" in result.failed_items[0]


async def test_two_of_three_quotes_found_reports_one_hallucination(
    enforcer: CitationEnforcer, mock_retriever: AsyncMock
) -> None:
    mock_retriever.retrieve_exact_quote.side_effect = [object(), object(), None]
    content = (
        '[Doc, SectionA]: "First quote text here"\n\n'
        '[Doc, SectionB]: "Second quote text here"\n\n'
        '[Doc, SectionC]: "Third quote text here"'
    )

    output = _make_output(content)
    result = await enforcer.validate(output, TENANT_ID, COVERAGE_ID)

    assert result.hallucination_count == 1
    hallucination_check = next(
        c for c in result.failed_checks if c.check_name == "quote_exists_in_rag"
    )
    assert hallucination_check.passed is False


# ── 10-12. check_no_unsourced_numbers ─────────────────────────────────────────


def test_number_with_citation_in_same_sentence_passes(enforcer: CitationEnforcer) -> None:
    content = (
        'Revenue was $383.3 billion in fiscal 2023. '
        '[AAPL, Business]: "Revenue was $383.3 billion in fiscal 2023"'
    )
    result = enforcer._check_no_unsourced_numbers(content)
    assert result.passed is True


def test_number_without_citation_fails(enforcer: CitationEnforcer) -> None:
    content = "Revenue was $383.3 billion in FY2023."
    result = enforcer._check_no_unsourced_numbers(content)
    assert result.passed is False
    assert len(result.failed_items) >= 1


def test_small_non_financial_number_does_not_trigger(enforcer: CitationEnforcer) -> None:
    content = "The company has 5 divisions."
    result = enforcer._check_no_unsourced_numbers(content)
    assert result.passed is True


# ── 13-15. check_no_future_speculation ────────────────────────────────────────


def test_speculation_without_citation_fails(enforcer: CitationEnforcer) -> None:
    content = "Management expects to grow revenue significantly next year."
    result = enforcer._check_no_future_speculation(content)
    assert result.passed is False
    assert len(result.failed_items) == 1


def test_speculation_with_direct_quote_citation_passes(enforcer: CitationEnforcer) -> None:
    content = (
        'Management expects to grow revenue next year '
        '[Transcript, Q4 2023]: "We expect revenues to grow in the coming year"'
    )
    result = enforcer._check_no_future_speculation(content)
    assert result.passed is True


def test_past_tense_statement_passes(enforcer: CitationEnforcer) -> None:
    content = "Revenue grew 12% in 2023."
    result = enforcer._check_no_future_speculation(content)
    assert result.passed is True


# ── 16-17. check_inference_labeling ───────────────────────────────────────────


def test_labeled_inference_passes(enforcer: CitationEnforcer) -> None:
    content = (
        "The company appears to be losing market share "
        "(inferred from [10-K, MD&A])."
    )
    result = enforcer._check_inference_labeling(content)
    assert result.passed is True


def test_unlabeled_inference_fails(enforcer: CitationEnforcer) -> None:
    content = "The company appears to be losing market share."
    result = enforcer._check_inference_labeling(content)
    assert result.passed is False
    assert len(result.failed_items) == 1


# ── 18-19. _build_retry_prompt ────────────────────────────────────────────────


def test_retry_prompt_includes_failed_check_names_and_items(
    enforcer: CitationEnforcer,
) -> None:
    from agents.shared.citation_enforcer import CheckResult

    checks = [
        CheckResult(
            check_name="citation_coverage",
            passed=False,
            details="Citation coverage: 60.0% (need >=95%)",
            failed_items=["Paragraph 2 has no citation"],
        ),
        CheckResult(
            check_name="no_unsourced_numbers",
            passed=False,
            details="1 numbers found without adjacent citations",
            failed_items=['"$383.3 billion" in: "Revenue was $383.3 billion in FY2023"'],
        ),
    ]

    prompt = enforcer._build_retry_prompt(checks, "original content")

    assert "CITATION COVERAGE" in prompt
    assert "NO UNSOURCED NUMBERS" in prompt
    assert "Paragraph 2 has no citation" in prompt
    assert "$383.3 billion" in prompt


def test_retry_prompt_includes_all_five_rules(enforcer: CitationEnforcer) -> None:
    from agents.shared.citation_enforcer import CheckResult

    checks = [
        CheckResult(check_name="quote_format", passed=False, details="bad format", failed_items=[])
    ]
    prompt = enforcer._build_retry_prompt(checks, "original content")

    assert "Every factual claim needs" in prompt
    assert "Every number needs a citation" in prompt
    assert "do not paraphrase" in prompt
    assert "Replace 'will grow/increase/expects to'" in prompt
    assert "Mark inferences" in prompt


# ── Acceptance criteria: full validate() flow ─────────────────────────────────


async def test_validate_approves_clean_fully_cited_output(
    enforcer: CitationEnforcer, mock_retriever: AsyncMock
) -> None:
    mock_retriever.retrieve_exact_quote.return_value = object()
    content = (
        'Revenue was $383.3 billion in fiscal 2023. '
        '[AAPL 10-K 2023, Business]: "Revenue was $383.3 billion in fiscal 2023"\n\n'
        'Net income was $97 billion for the year. '
        '[AAPL 10-K 2023, Financials]: "Net income was $97 billion for the year"'
    )
    output = _make_output(content)

    result = await enforcer.validate(output, TENANT_ID, COVERAGE_ID)

    assert result.approved is True
    assert result.enforcer_status == "approved"
    assert result.retry_prompt is None


async def test_validate_rejects_hallucinated_output(
    enforcer: CitationEnforcer, mock_retriever: AsyncMock
) -> None:
    mock_retriever.retrieve_exact_quote.return_value = None
    content = (
        'Revenue was $383.3 billion in fiscal 2023. '
        '[AAPL 10-K 2023, Business]: "Revenue was $383.3 billion in fiscal 2023"'
    )
    output = _make_output(content)

    result = await enforcer.validate(output, TENANT_ID, COVERAGE_ID)

    assert result.approved is False
    assert result.hallucination_count == 1
    assert result.retry_prompt is not None
