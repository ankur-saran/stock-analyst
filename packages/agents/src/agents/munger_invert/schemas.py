"""Output schema for the Munger Invert bear case.

Mirrors ``agents.lynch_pitch.schemas`` exactly in enforcement shape --
``AnswerWithCitation.require_citation_or_not_found`` and
``MungerCase.validate_all_8_questions`` are the same mechanical guardrails,
just against the 8 adversarial questions instead of the 8 Lynch questions.
There is no company-type classification here: inversion doesn't care what
kind of grower the company is, only how the thesis fails.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator


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
        # Adversarial tone is not an excuse for an uncited claim -- the same
        # discipline Lynch Pitch enforces applies here.
        if has_content and self.citation_coverage_pct < 0.5 and not self.not_found_items:
            raise ValueError(
                f"Q{self.question_number} has content but no citations or Not Found declarations"
            )
        return self


class MungerCase(BaseModel):
    coverage_id: str
    company_name: str
    ticker: str
    answers: list[AnswerWithCitation]  # exactly 8
    all_citations: list[dict[str, Any]]
    citation_coverage_pct: float
    word_count: int
    generated_at: datetime
    llm_used: str

    @model_validator(mode="after")
    def validate_all_8_questions(self) -> "MungerCase":
        assert len(self.answers) == 8, f"Must answer all 8 questions, got {len(self.answers)}"
        assert self.citation_coverage_pct >= 0.90, (
            f"Citation coverage {self.citation_coverage_pct:.1%} too low -- minimum 90% for storage "
            "(Citation Enforcer will enforce the 95% gate)"
        )
        return self
