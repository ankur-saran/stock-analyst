"""Output schema for a single KPI extraction the LLM returns.

Deliberately thin -- unlike Lynch Pitch/Munger Invert's prose schemas, there
is no citation-coverage gate here. Malformed items are dropped by the caller
(``agents.kpi_tracker.agent``) rather than raising, since one bad item in a
JSON array from an LLM shouldn't discard every good item alongside it.
"""
from __future__ import annotations

from pydantic import BaseModel


class ExtractedKPI(BaseModel):
    kpi_name: str
    raw_value: str
    period: str
    exact_quote: str
    document_name: str
    section: str
    page_number: int | None = None
