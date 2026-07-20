"""Unit tests for FinancialNormalizer."""
from __future__ import annotations

import math

import pytest

from rag.ingestion.parsers.financial_normalizer import FinancialNormalizer

normalizer = FinancialNormalizer()


# ── normalize_value ───────────────────────────────────────────────────────────

# (raw, context_unit, expected_value, expected_unit, expected_currency, expected_negative)
VALUE_CASES = [
    ("$1.23B", None, 1230.0, "USD_millions", "USD", False),
    ("$1,234.5 million", None, 1234.5, "USD_millions", "USD", False),
    ("1.23 billion", None, 1230.0, "USD_millions", "USD", False),
    ("$2B", None, 2000.0, "USD_millions", "USD", False),
    ("$1.5M", None, 1.5, "USD_millions", "USD", False),
    ("$500K", None, 0.5, "USD_millions", "USD", False),
    ("$2.5 thousand", None, 0.0025, "USD_millions", "USD", False),
    ("$0", None, 0.0, "USD_millions", "USD", False),
    ("(452)", None, 452.0, "USD_millions", "USD", True),
    ("(1.2B)", None, 1200.0, "USD_millions", "USD", True),
    ("-452", None, 452.0, "USD_millions", "USD", True),
    ("−452", None, 452.0, "USD_millions", "USD", True),  # unicode minus
    ("–1.2B", None, 1200.0, "USD_millions", "USD", True),  # en dash
    ("$(452)", None, 452.0, "USD_millions", "USD", True),
    ("12.3%", None, 12.3, "percentage", None, False),
    ("(12.3)%", None, 12.3, "percentage", None, True),
    ("4.5M shares", None, 4_500_000.0, "count", None, False),
    ("4,500,000 shares", None, 4_500_000.0, "count", None, False),
    ("$1,234", "thousands", 1.234, "USD_millions", "USD", False),
    ("1,234", "millions", 1234.0, "USD_millions", "USD", False),
    ("€1.5B", None, 1500.0, "EUR_millions", "EUR", False),
    ("£2.1B", None, 2100.0, "GBP_millions", "GBP", False),
    ("2.3x", None, 2.3, "ratio", None, False),
]


@pytest.mark.parametrize(
    "raw,context_unit,expected_value,expected_unit,expected_currency,expected_negative",
    VALUE_CASES,
)
def test_normalize_value(
    raw: str,
    context_unit: str | None,
    expected_value: float,
    expected_unit: str,
    expected_currency: str | None,
    expected_negative: bool,
) -> None:
    result = normalizer.normalize_value(raw, context_unit=context_unit)

    assert result.numeric_value == pytest.approx(expected_value)
    assert result.unit == expected_unit
    assert result.currency == expected_currency
    assert result.is_negative is expected_negative
    assert result.confidence > 0.0


@pytest.mark.parametrize("raw", ["—", "-", "n/m", "n/a", "N/A", "NM", "N/M"])
def test_normalize_value_not_available_returns_nan_with_zero_confidence(raw: str) -> None:
    result = normalizer.normalize_value(raw)

    assert math.isnan(result.numeric_value)
    assert result.confidence == 0.0


def test_normalize_value_never_raises_on_garbage_input() -> None:
    for raw in ["", "   ", "???", "abc def", None]:  # type: ignore[list-item]
        result = normalizer.normalize_value(raw)  # type: ignore[arg-type]
        assert result.confidence == 0.0


# ── normalize_period ──────────────────────────────────────────────────────────

# (raw, expected_label, expected_type, expected_fiscal_year, expected_quarter)
PERIOD_CASES = [
    ("fiscal year 2024", "FY2024", "annual", 2024, None),
    ("FY2024", "FY2024", "annual", 2024, None),
    ("FY'24", "FY2024", "annual", 2024, None),
    ("year ended December 31, 2024", "FY2024", "annual", 2024, None),
    ("year ended Dec 31, 2024", "FY2024", "annual", 2024, None),
    ("twelve months ended December 31, 2024", "FY2024", "annual", 2024, None),
    ("twelve months ended Dec 31, 2023", "FY2023", "annual", 2023, None),
    ("annual 2024", "FY2024", "annual", 2024, None),
    ("Q1 2024", "Q1 2024", "quarterly", 2024, 1),
    ("Q1'24", "Q1 2024", "quarterly", 2024, 1),
    ("Q3'24", "Q3 2024", "quarterly", 2024, 3),
    ("first quarter 2024", "Q1 2024", "quarterly", 2024, 1),
    ("second quarter 2024", "Q2 2024", "quarterly", 2024, 2),
    ("fourth quarter 2024", "Q4 2024", "quarterly", 2024, 4),
    ("third quarter fiscal 2024", "Q3 2024", "quarterly", 2024, 3),
    ("three months ended March 31, 2024", "Q1 2024", "quarterly", 2024, 1),
    ("three months ended Mar 31, 2024", "Q1 2024", "quarterly", 2024, 1),
]


@pytest.mark.parametrize(
    "raw,expected_label,expected_type,expected_fiscal_year,expected_quarter", PERIOD_CASES
)
def test_normalize_period(
    raw: str,
    expected_label: str,
    expected_type: str,
    expected_fiscal_year: int,
    expected_quarter: int | None,
) -> None:
    result = normalizer.normalize_period(raw)

    assert result.period_label == expected_label
    assert result.period_type == expected_type
    assert result.fiscal_year == expected_fiscal_year
    assert result.quarter == expected_quarter


def test_normalize_period_raises_on_unrecognized_format() -> None:
    with pytest.raises(ValueError):
        normalizer.normalize_period("sometime last summer")


# ── extract_values_from_text ─────────────────────────────────────────────────


def test_extract_values_from_text_finds_multiple_metrics() -> None:
    text = "Revenue grew to $1.23B, up 12.3%, while shares outstanding reached 4.5M shares."

    results = normalizer.extract_values_from_text(text)

    units = [r[1].unit for r in results]
    assert "USD_millions" in units
    assert "percentage" in units
    assert "count" in units


def test_extract_values_from_text_ignores_bare_numbers_without_financial_anchor() -> None:
    text = "The company operates 2024 stores across 50 states."

    results = normalizer.extract_values_from_text(text)

    assert results == []
