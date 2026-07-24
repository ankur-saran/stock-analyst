"""Output schema for the Lynch Pitch.

``AnswerWithCitation.require_citation_or_not_found`` and
``LynchPitch.validate_all_8_questions`` are the enforcement points for the
system prompt's evidence discipline -- if the LLM drifts (a claim with no
citation and no "Not found" declaration, fewer than 8 questions answered,
overall coverage below the storage floor), pydantic raises loudly here
instead of the malformed pitch silently reaching storage or the UI. The
Citation Enforcer still runs afterward and applies its own, stricter 95%
gate -- this schema's 90% floor is just the minimum sanity bar for a pitch
to be worth storing and retried against at all.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, model_validator


class CompanyType(str, Enum):
    SLOW_GROWER = "slow_grower"
    STALWART = "stalwart"
    FAST_GROWER = "fast_grower"
    CYCLICAL = "cyclical"
    TURNAROUND = "turnaround"
    ASSET_PLAY = "asset_play"


class AnswerWithCitation(BaseModel):
    question_number: int
    question_text: str
    answer_text: str
    citations: list[dict[str, Any]]
    citation_coverage_pct: float
    not_found_items: list[str]  # items where the agent said "Not found in uploaded documents"

    @model_validator(mode="after")
    def require_citation_or_not_found(self) -> "AnswerWithCitation":
        has_content = bool(self.answer_text.strip())
        # Each answer must either have adequate citation coverage OR explicitly
        # declare the data wasn't found -- an uncited, un-declared claim is the
        # one shape this schema refuses to let through.
        if has_content and self.citation_coverage_pct < 0.5 and not self.not_found_items:
            raise ValueError(
                f"Q{self.question_number} has content but no citations or Not Found declarations"
            )
        return self


class LynchPitch(BaseModel):
    coverage_id: str
    company_name: str
    ticker: str
    answers: list[AnswerWithCitation]  # exactly 8
    company_type: CompanyType
    all_citations: list[dict[str, Any]]
    citation_coverage_pct: float
    word_count: int
    generated_at: datetime
    llm_used: str

    @model_validator(mode="after")
    def validate_all_8_questions(self) -> "LynchPitch":
        assert len(self.answers) == 8, f"Must answer all 8 questions, got {len(self.answers)}"
        assert self.citation_coverage_pct >= 0.90, (
            f"Citation coverage {self.citation_coverage_pct:.1%} too low -- minimum 90% for storage "
            "(Citation Enforcer will enforce the 95% gate)"
        )
        return self
