"""Output schema for the industry primer.

``IndustryPrimer.validate_structure`` is the enforcement point for the
system prompt's mandatory structure — if the LLM drifts (fewer than 6
sections, a stray synthesis bullet, an out-of-range word count), pydantic
raises loudly here instead of the malformed primer silently reaching
storage or the UI.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator


class IndustryPrimerSection(BaseModel):
    section_number: int
    section_name: str
    content: str
    citations: list[dict[str, Any]]
    word_count: int


class InvestorSynthesisBullet(BaseModel):
    topic: str  # "core_economic_engine", "primary_growth_lever", etc.
    content: str
    citations: list[dict[str, Any]]


class IndustryPrimer(BaseModel):
    industry_id: str
    industry_name: str
    sections: list[IndustryPrimerSection]  # 6 sections
    investor_synthesis: list[InvestorSynthesisBullet]  # exactly 5 bullets
    all_citations: list[dict[str, Any]]
    word_count: int
    llm_used: str
    created_at: datetime
    confidence_score: float  # 0-1: (cited_claims / total_claims)

    @model_validator(mode="after")
    def validate_structure(self) -> "IndustryPrimer":
        assert len(self.sections) == 6, "Must have exactly 6 sections"
        assert len(self.investor_synthesis) == 5, "Must have exactly 5 synthesis bullets"
        assert 1200 <= self.word_count <= 2000, f"Word count {self.word_count} outside 1200-1800 range"
        return self
