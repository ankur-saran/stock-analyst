"""Normalizes raw financial values and periods extracted from filing text/tables.

Values in SEC filings show up in wildly inconsistent forms — "$1.23B", "1,234.5
million", "(452)" — across documents and even within the same table's footnotes.
KPI Tracker needs all of them collapsed onto one scale (USD millions) so a
time-series is comparable regardless of which filing a number was pulled from.

Magnitude context (whether a bare number like "1,234" means thousands or
millions) lives in table/column headers, not in the value string itself, so
callers that know it must pass ``context_unit`` explicitly — this module does
not try to infer it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_UNICODE_MINUS = "−"
_EN_DASH = "–"
_NEGATIVE_PREFIXES = ("-", _UNICODE_MINUS, _EN_DASH)

_CURRENCY_SYMBOLS = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
_CURRENCY_WORDS = {"usd": "USD", "eur": "EUR", "gbp": "GBP", "jpy": "JPY"}

# Multipliers to bring a value onto a USD-millions scale.
_MONETARY_SUFFIX_MULTIPLIER = {
    "b": 1000.0, "bn": 1000.0, "billion": 1000.0,
    "m": 1.0, "mm": 1.0, "million": 1.0,
    "k": 0.001, "thousand": 0.001,
}
# Multipliers for raw counts (shares), which are never expressed "in millions".
_COUNT_SUFFIX_MULTIPLIER = {
    "b": 1_000_000_000.0, "bn": 1_000_000_000.0, "billion": 1_000_000_000.0,
    "m": 1_000_000.0, "mm": 1_000_000.0, "million": 1_000_000.0,
    "k": 1_000.0, "thousand": 1_000.0,
}

_CONTEXT_UNIT_MULTIPLIER = {"thousands": 0.001, "millions": 1.0, "billions": 1000.0}

_NUMBER_SUFFIX_RE = re.compile(r"^([\d,]*\.?\d+)\s*([a-zA-Z]+)?$")
_PERCENT_STRIP_RE = re.compile(r"%|percent|pct", re.IGNORECASE)
_PERCENT_DETECT_RE = re.compile(r"%|\bpercent\b|\bpct\b", re.IGNORECASE)
_SHARES_DETECT_RE = re.compile(r"\bshares?\b", re.IGNORECASE)
_SHARES_STRIP_RE = re.compile(r"\bshares?\b", re.IGNORECASE)
_RATIO_RE = re.compile(r"^([\d,]*\.?\d+)\s*x$", re.IGNORECASE)
_CURRENCY_WORD_RE = re.compile(r"\b(usd|eur|gbp|jpy)\b", re.IGNORECASE)
_HAS_DIGIT_RE = re.compile(r"\d")

_QUARTER_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4}
_MONTH_TO_QUARTER = {
    1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4,
}
_MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}

_Q_RE = re.compile(r"\bQ([1-4])\s*'?\s*(\d{2,4})\b", re.IGNORECASE)
_WORD_Q_RE = re.compile(
    r"\b(first|second|third|fourth)\s+quarter\b(?:\s+(?:fiscal\s+)?(\d{4}))?", re.IGNORECASE
)
_THREE_MONTHS_RE = re.compile(
    r"\bthree\s+months\s+ended\s+([A-Za-z]+)\.?\s+\d{1,2},?\s+(\d{4})", re.IGNORECASE
)
_TWELVE_MONTHS_RE = re.compile(
    r"\btwelve\s+months\s+ended\s+[A-Za-z]+\.?\s+\d{1,2},?\s+(\d{4})", re.IGNORECASE
)
_YEAR_ENDED_RE = re.compile(
    r"\byear\s+ended\s+[A-Za-z]+\.?\s+\d{1,2},?\s+(\d{4})", re.IGNORECASE
)
_FY_RE = re.compile(r"\bFY\s*'?\s*(\d{2,4})\b", re.IGNORECASE)
_FISCAL_YEAR_RE = re.compile(r"\bfiscal\s+year\s+(\d{4})\b", re.IGNORECASE)
_ANNUAL_RE = re.compile(r"\bannual\s+(\d{4})\b", re.IGNORECASE)

# Alternatives requiring a financial "anchor" (currency, %, magnitude word, or
# "shares") so we don't flag every bare number in a paragraph.
_CURRENCY_VALUE_RE = re.compile(
    r"\(?[-−–]?[\$€£¥]\s?[\d,]+(?:\.\d+)?\)?"
    r"\s?(?:billion|bn|million|mm|thousand|k|b|m)?\b",
    re.IGNORECASE,
)
_MAGNITUDE_VALUE_RE = re.compile(
    r"\(?[-−–]?[\d,]+(?:\.\d+)?\)?\s?(?:billion|bn|million|thousand)\b",
    re.IGNORECASE,
)
_PERCENT_VALUE_RE = re.compile(
    r"\(?[-−–]?[\d,]+(?:\.\d+)?\)?\s?(?:%|percent\b)", re.IGNORECASE
)
_SHARE_VALUE_RE = re.compile(
    r"[-−–]?[\d,]+(?:\.\d+)?\s?(?:million|billion|thousand|mm|bn|[mbk])?\s*shares?\b",
    re.IGNORECASE,
)
_SCAN_PATTERNS = [_CURRENCY_VALUE_RE, _MAGNITUDE_VALUE_RE, _PERCENT_VALUE_RE, _SHARE_VALUE_RE]


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class NormalizedValue:
    raw_string: str
    numeric_value: float
    unit: str
    currency: str | None
    is_negative: bool
    confidence: float


@dataclass
class NormalizedPeriod:
    raw_string: str
    period_label: str
    period_type: str
    fiscal_year: int
    quarter: int | None


class FinancialNormalizer:
    # ── Values ────────────────────────────────────────────────────────────────

    def normalize_value(self, raw: str, context_unit: str | None = None) -> NormalizedValue:
        try:
            return self._normalize_value_impl(raw, context_unit)
        except Exception:
            return NormalizedValue(
                raw_string=raw, numeric_value=float("nan"), unit="unknown",
                currency=None, is_negative=False, confidence=0.0,
            )

    def _normalize_value_impl(self, raw: str, context_unit: str | None) -> NormalizedValue:
        text = raw.strip()

        if not text or not _HAS_DIGIT_RE.search(text):
            return NormalizedValue(raw, float("nan"), "unknown", None, False, 0.0)

        currency: str | None = None
        for sym, code in _CURRENCY_SYMBOLS.items():
            if sym in text:
                currency = code
                text = text.replace(sym, "")
                break
        if currency is None:
            word_match = _CURRENCY_WORD_RE.search(text)
            if word_match:
                currency = _CURRENCY_WORDS[word_match.group(1).lower()]
                text = text[: word_match.start()] + text[word_match.end():]
        text = text.strip()

        is_negative = False
        paren_match = re.match(r"^\((.*)\)(%?)$", text)
        if paren_match:
            is_negative = True
            text = (paren_match.group(1).strip() + paren_match.group(2)).strip()
        elif text[:1] in _NEGATIVE_PREFIXES:
            is_negative = True
            text = text[1:].strip()

        if _PERCENT_DETECT_RE.search(text):
            number = self._to_float(_PERCENT_STRIP_RE.sub("", text).strip())
            if number is None:
                return NormalizedValue(raw, float("nan"), "unknown", None, is_negative, 0.0)
            return NormalizedValue(raw, number, "percentage", None, is_negative, 0.9)

        if _SHARES_DETECT_RE.search(text):
            value = self._parse_magnitude(
                _SHARES_STRIP_RE.sub("", text).strip(), _COUNT_SUFFIX_MULTIPLIER
            )
            if value is None:
                return NormalizedValue(raw, float("nan"), "unknown", None, is_negative, 0.0)
            return NormalizedValue(raw, value, "count", None, is_negative, 0.9)

        ratio_match = _RATIO_RE.match(text)
        if ratio_match:
            number = self._to_float(ratio_match.group(1))
            if number is None:
                return NormalizedValue(raw, float("nan"), "unknown", None, is_negative, 0.0)
            return NormalizedValue(raw, number, "ratio", None, is_negative, 0.85)

        value_millions = self._parse_monetary(text, context_unit)
        if value_millions is None:
            return NormalizedValue(raw, float("nan"), "unknown", currency, is_negative, 0.0)

        final_currency = currency or "USD"
        return NormalizedValue(
            raw, value_millions, f"{final_currency}_millions", final_currency, is_negative, 0.9
        )

    def _parse_monetary(self, text: str, context_unit: str | None) -> float | None:
        match = _NUMBER_SUFFIX_RE.match(text.strip())
        if not match:
            return None
        number = self._to_float(match.group(1))
        if number is None:
            return None

        suffix = match.group(2)
        if suffix:
            multiplier = _MONETARY_SUFFIX_MULTIPLIER.get(suffix.lower())
            if multiplier is None:
                return None
            return number * multiplier

        multiplier = _CONTEXT_UNIT_MULTIPLIER.get(context_unit or "", 1.0)
        return number * multiplier

    def _parse_magnitude(self, text: str, multipliers: dict[str, float]) -> float | None:
        match = _NUMBER_SUFFIX_RE.match(text.strip())
        if not match:
            return None
        number = self._to_float(match.group(1))
        if number is None:
            return None

        suffix = match.group(2)
        if not suffix:
            return number

        multiplier = multipliers.get(suffix.lower())
        if multiplier is None:
            return None
        return number * multiplier

    @staticmethod
    def _to_float(text: str) -> float | None:
        try:
            return float(text.replace(",", ""))
        except (ValueError, AttributeError):
            return None

    def extract_values_from_text(self, text: str) -> list[tuple[str, NormalizedValue]]:
        matches: list[tuple[int, int, str]] = []
        for pattern in _SCAN_PATTERNS:
            for m in pattern.finditer(text):
                matches.append((m.start(), m.end(), m.group(0)))

        matches.sort(key=lambda t: (t[0], -(t[1] - t[0])))

        kept: list[tuple[int, int, str]] = []
        for start, end, matched in matches:
            if any(start < e and s < end for s, e, _ in kept):
                continue
            kept.append((start, end, matched))
        kept.sort(key=lambda t: t[0])

        return [
            (matched.strip(), self.normalize_value(matched.strip())) for _, _, matched in kept
        ]

    # ── Periods ───────────────────────────────────────────────────────────────

    def normalize_period(self, raw: str) -> NormalizedPeriod:
        text = raw.strip()

        q_match = _Q_RE.search(text)
        if q_match:
            return self._quarterly(raw, self._expand_year(q_match.group(2)), int(q_match.group(1)))

        word_q_match = _WORD_Q_RE.search(text)
        if word_q_match:
            quarter = _QUARTER_WORDS[word_q_match.group(1).lower()]
            year_str = word_q_match.group(2)
            if year_str is None:
                year_match = re.search(r"\d{4}", text)
                if not year_match:
                    raise ValueError(f"Cannot determine year for period: {raw!r}")
                year_str = year_match.group(0)
            return self._quarterly(raw, int(year_str), quarter)

        three_months_match = _THREE_MONTHS_RE.search(text)
        if three_months_match:
            month = _MONTH_NAMES.get(three_months_match.group(1).lower())
            if month is None:
                raise ValueError(f"Unrecognized month in period: {raw!r}")
            return self._quarterly(
                raw, int(three_months_match.group(2)), _MONTH_TO_QUARTER[month]
            )

        twelve_months_match = _TWELVE_MONTHS_RE.search(text)
        if twelve_months_match:
            return self._annual(raw, int(twelve_months_match.group(1)))

        year_ended_match = _YEAR_ENDED_RE.search(text)
        if year_ended_match:
            return self._annual(raw, int(year_ended_match.group(1)))

        fy_match = _FY_RE.search(text)
        if fy_match:
            return self._annual(raw, self._expand_year(fy_match.group(1)))

        fiscal_year_match = _FISCAL_YEAR_RE.search(text)
        if fiscal_year_match:
            return self._annual(raw, int(fiscal_year_match.group(1)))

        annual_match = _ANNUAL_RE.search(text)
        if annual_match:
            return self._annual(raw, int(annual_match.group(1)))

        raise ValueError(f"Unrecognized period format: {raw!r}")

    @staticmethod
    def _quarterly(raw: str, year: int, quarter: int) -> NormalizedPeriod:
        return NormalizedPeriod(raw, f"Q{quarter} {year}", "quarterly", year, quarter)

    @staticmethod
    def _annual(raw: str, year: int) -> NormalizedPeriod:
        return NormalizedPeriod(raw, f"FY{year}", "annual", year, None)

    @staticmethod
    def _expand_year(raw_year: str) -> int:
        digits = raw_year.strip("'")
        value = int(digits)
        return 2000 + value if value < 100 else value
