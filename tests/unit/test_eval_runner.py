"""Unit tests for the pure-function/check-evaluation logic in eval/runners/run_eval.py.

Everything network- or DB-backed (task dispatch, polling, the live
CitationEnforcer pass) is exercised only against a running stack, not here --
these tests cover the part that's actually deterministic and worth pinning:
how a dataset's declared checks turn into pass/fail against a fixed string of
agent output.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.runners.run_eval import (  # noqa: E402
    CaseResult,
    CheckResult,
    EvalRunner,
    EvalReport,
    _citation_coverage,
    _metric_stated_as_number,
    _question_blocks,
)


def _runner() -> EvalRunner:
    """A check-only EvalRunner -- bypasses __init__ so no network/DB/dataset I/O happens."""
    return EvalRunner.__new__(EvalRunner)


# ── _question_blocks / _citation_coverage / _metric_stated_as_number ────────


def test_question_blocks_splits_on_headers() -> None:
    content = (
        "### Q1: What does this company do?\n"
        "Sells widgets.\n\n"
        "### Q3: How does the company make money?\n"
        "Not found in uploaded documents.\n"
    )
    blocks = _question_blocks(content)
    assert set(blocks) == {1, 3}
    assert "widgets" in blocks[1]
    assert "not found" in blocks[3].lower()


def test_citation_coverage_all_cited() -> None:
    content = 'Revenue was $1 million. [Doc, Section]: "Revenue was $1 million"'
    assert _citation_coverage(content) == 1.0


def test_citation_coverage_uncited_number_paragraph() -> None:
    content = "Revenue was $1 million.\n\nCosts were $2 million with no citation at all here."
    assert _citation_coverage(content) == 0.0


def test_metric_stated_as_number_true_when_percent_present() -> None:
    assert _metric_stated_as_number("Gross margin was 42.1% this year.", "gross margin") is True


def test_metric_stated_as_number_false_when_no_percent() -> None:
    assert _metric_stated_as_number("Revenue was $42.1 million this year.", "gross margin") is False


# ── _run_checks ───────────────────────────────────────────────────────────────


def test_run_checks_must_answer_questions_flags_missing_header() -> None:
    runner = _runner()
    case = {"must_answer_questions": [1, 2]}
    content = "### Q1: What does this company do?\nSells widgets."

    checks = runner._run_checks(case, content)

    by_name = {c.name: c for c in checks}
    assert by_name["Q1_answered"].passed is True
    assert by_name["Q2_answered"].passed is False


def test_run_checks_must_not_contain_forbidden_phrase() -> None:
    runner = _runner()
    case = {"must_not_contain": ["exciting opportunity"]}
    content = "This is an exciting opportunity for investors."

    checks = runner._run_checks(case, content)

    assert any(not c.passed for c in checks)


def test_run_checks_must_contain_not_found_token() -> None:
    runner = _runner()
    case = {"must_contain_not_found": ["Q4"]}
    content = (
        "### Q4: Balance sheet health\n"
        "Not found in uploaded documents.\n"
    )

    checks = runner._run_checks(case, content)

    check = next(c for c in checks if c.name == "Q4_states_not_found")
    assert check.passed is True


def test_run_checks_dynamic_qn_must_contain_not_found_key() -> None:
    runner = _runner()
    case = {"q3_must_contain_not_found": True}
    content = "### Q3: Margins\nNot found in uploaded documents.\n"

    checks = runner._run_checks(case, content)

    check = next(c for c in checks if c.name == "q3_must_contain_not_found")
    assert check.passed is True


def test_run_checks_dynamic_must_not_state_metric_flags_fabrication() -> None:
    runner = _runner()
    case = {"must_not_state_gross_margin": True}
    content = "Gross margin was 41.2% for the period, though no source discloses it."

    checks = runner._run_checks(case, content)

    check = next(c for c in checks if c.name == "must_not_state_gross_margin")
    assert check.passed is False


def test_run_checks_dynamic_must_not_state_metric_passes_when_absent() -> None:
    runner = _runner()
    case = {"must_not_state_gross_margin": True}
    content = "Revenue was $214.6 million. Gross margin data was not disclosed in the filing."

    checks = runner._run_checks(case, content)

    check = next(c for c in checks if c.name == "must_not_state_gross_margin")
    assert check.passed is True


def test_run_checks_citation_coverage_uses_case_minimum() -> None:
    runner = _runner()
    content = "Revenue was $1 million.\n\nCosts were $2 million, no citation."  # 0.0 coverage

    failing = next(c for c in runner._run_checks({"min_citation_coverage": 0.5}, content) if c.name == "citation_coverage")
    assert failing.passed is False

    passing = next(c for c in runner._run_checks({"min_citation_coverage": 0.0}, content) if c.name == "citation_coverage")
    assert passing.passed is True


def test_run_checks_max_word_count() -> None:
    runner = _runner()
    case = {"max_word_count": 3}
    content = "one two three four five"

    checks = runner._run_checks(case, content)

    check = next(c for c in checks if c.name == "max_word_count")
    assert check.passed is False


def test_run_checks_all_citations_must_match_regex_flags_short_quote() -> None:
    runner = _runner()
    case = {"all_citations_must_match_regex": r'\[[^\]]+,\s*[^\]]+\]:\s*"[^"]{10,}"'}
    content = '[Doc, Section]: "short"'  # quote under the 10-char strict minimum

    checks = runner._run_checks(case, content)

    check = next(c for c in checks if c.name == "citation_format")
    assert check.passed is False


def test_run_checks_must_start_with_short_circuits_other_checks() -> None:
    runner = _runner()
    case = {
        "must_start_with": "PREREQUISITE_MISSING",
        "skip_citation_checks": True,
        "must_answer_questions": [1, 2, 3],
    }
    content = "PREREQUISITE_MISSING: no prior filing to compare against"

    checks = runner._run_checks(case, content)

    assert len(checks) == 1
    assert checks[0].name == "must_start_with"
    assert checks[0].passed is True


def test_run_checks_min_kpis_upserted_parses_summary_count() -> None:
    runner = _runner()
    case = {"min_kpis_upserted": 5}
    content = "7 KPI value(s) upserted across 3 document(s)."

    checks = runner._run_checks(case, content)

    check = next(c for c in checks if c.name == "min_kpis_upserted")
    assert check.passed is True


# ── EvalReport aggregate properties ─────────────────────────────────────────


def test_eval_report_aggregates() -> None:
    report = EvalReport(
        agent="lynch_pitch",
        results=[
            CaseResult(
                test_id="LP-001", name="ok", passed=True,
                checks=[CheckResult("x", True, "ok")],
                citation_coverage_pct=1.0, hallucination_count=0, paraphrase_count=1,
                citations_found=4, latency_ms=1000, llm_used="claude-sonnet-5", tokens_used=1000,
            ),
            CaseResult(
                test_id="LP-002", name="bad", passed=False,
                checks=[CheckResult("x", False, "bad")],
                citation_coverage_pct=0.5, hallucination_count=1, paraphrase_count=0,
                citations_found=4, latency_ms=2000, llm_used="claude-sonnet-5", tokens_used=2000,
            ),
        ],
    )

    assert report.pass_rate == 0.5
    assert report.avg_citation_coverage == 0.75
    assert report.avg_latency_ms == 1500
    assert report.hallucination_rate == 1 / 8
    assert report.total_paraphrase_warnings == 1


def test_eval_report_empty_results_does_not_divide_by_zero() -> None:
    report = EvalReport(agent="lynch_pitch", results=[])
    assert report.pass_rate == 0.0
    assert report.avg_citation_coverage == 0.0
    assert report.avg_latency_ms == 0.0
    assert report.hallucination_rate == 0.0
