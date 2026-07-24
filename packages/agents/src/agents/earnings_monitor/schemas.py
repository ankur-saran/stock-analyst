"""Output schema for the Earnings Monitor's quarterly update.

Same enforcement shape as Lynch Pitch/Munger Invert -- a per-section
citation floor plus an overall 90% storage floor -- applied to the 3 fixed
sections (guidance vs reality, KPI analysis, what changed) instead of 8
questions, plus the 3-verdict FINAL SUMMARY this agent's whole output boils
down to for the platform's management-credibility track record.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, model_validator


class ExecutionVerdict(str, Enum):
    IMPROVING = "Improving"
    STABLE = "Stable"
    DETERIORATING = "Deteriorating"


class CredibilityVerdict(str, Enum):
    STRONG = "Strong"
    MIXED = "Mixed"
    WEAK = "Weak"


class MomentumVerdict(str, Enum):
    BETTER = "Better"
    SAME = "Same"
    WORSE = "Worse"


class QuarterlySection(BaseModel):
    section_number: int
    section_name: str
    content: str
    citations: list[dict[str, Any]]

    @model_validator(mode="after")
    def require_citation_or_not_found(self) -> "QuarterlySection":
        has_content = bool(self.content.strip())
        has_not_found = "not found in uploaded documents" in self.content.lower()
        if has_content and not self.citations and not has_not_found:
            raise ValueError(f"Section {self.section_number} has content but no citations")
        return self


class QuarterlyUpdate(BaseModel):
    coverage_id: str
    company_name: str
    ticker: str
    sections: list[QuarterlySection]  # exactly 3
    execution_vs_expectations: ExecutionVerdict
    management_credibility: CredibilityVerdict
    business_momentum: MomentumVerdict
    all_citations: list[dict[str, Any]]
    citation_coverage_pct: float
    word_count: int
    generated_at: datetime
    llm_used: str

    @model_validator(mode="after")
    def validate_all_3_sections(self) -> "QuarterlyUpdate":
        assert len(self.sections) == 3, f"Must produce all 3 sections, got {len(self.sections)}"
        assert self.citation_coverage_pct >= 0.90, (
            f"Citation coverage {self.citation_coverage_pct:.1%} too low -- minimum 90% for storage "
            "(Citation Enforcer will enforce the 95% gate)"
        )
        return self
