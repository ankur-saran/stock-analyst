"""PDF coverage report generation (WeasyPrint + Jinja2).

Pulls every enforcer-approved ``research_outputs`` row for a coverage (plus
its KPI time-series and analyst notes), renders them into a single HTML
document, and rasterizes that to PDF via WeasyPrint. Only the latest
approved version of each output_type is included — earlier versions exist
for audit purposes but have no place in a client-facing report.

Citation footnotes: every agent output body (and the analyst notes) carries
inline ``[Document Name, Section]: "exact quote"`` citations in the same
grammar the Citation Enforcer requires (see
``agents.shared.citation_enforcer.CITATION_PATTERN``). This module rewrites
each occurrence into a numbered footnote marker and accumulates a single,
report-wide, de-duplicated citation list rendered at the end — including
occurrences inside markdown-style pipe tables embedded in a section's body,
since the regex substitution runs across the whole content string before any
table/paragraph structure is parsed out.
"""
from __future__ import annotations

import asyncio
import html as _html
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from weasyprint import HTML

from shared.models import (
    Coverage,
    CoverageNotes,
    KpiTimeseries,
    OutputTypeEnum,
    ResearchOutput,
)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"

_SECTION_ORDER: list[OutputTypeEnum] = [
    OutputTypeEnum.industry_primer,
    OutputTypeEnum.lynch_pitch,
    OutputTypeEnum.munger_invert,
    OutputTypeEnum.quarterly_update,
]

_SECTION_TITLES: dict[OutputTypeEnum, str] = {
    OutputTypeEnum.industry_primer: "Industry Primer",
    OutputTypeEnum.lynch_pitch: "Bull Case (Lynch Pitch)",
    OutputTypeEnum.munger_invert: "Bear Case (Munger Invert)",
    OutputTypeEnum.quarterly_update: "Latest Quarterly Update",
}

# Same citation grammar the Citation Enforcer requires in agent output:
# [Document Name, Section]: "exact quote" — see
# agents.shared.citation_enforcer.CITATION_PATTERN. Duplicated rather than
# imported: `agents` depends on heavy LLM/LangGraph packages this API-only
# module has no other reason to pull in.
_CITATION_PATTERN = re.compile(r'\[([^\]\n]+),\s*([^\]\n]+)\]:\s*"([^"]+)"')

# Substituted in place of a citation match, then converted to the final
# <sup> footnote marker *after* the surrounding prose has been HTML-escaped
# — avoids the citation's literal double quotes turning into `&quot;` before
# the regex gets a second pass.
_PLACEHOLDER_RE = re.compile(r"@@CITE(\d+)@@")

# A block of lines that are all markdown-style pipe-table rows (an optional
# leading "|", cells separated by "|"). The Lynch Pitch / Munger Invert /
# Earnings Monitor prompts occasionally have agents emit simple tables like
# this for comparison data; citations inside their cells go through the same
# placeholder substitution as body prose before this module ever inspects
# table structure, so they get correctly numbered footnotes too.
_TABLE_LINE_RE = re.compile(r"^\s*\|.*\|\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?$")

# Font embedding: WeasyPrint will happily embed any TTF/OTF supplied as
# base64, but Georgia itself is a Microsoft-licensed font this repo has no
# right to redistribute — so unless a licensed serif font file is dropped at
# the path below at build time, the template falls back to a plain CSS font
# stack (Georgia if present on the host, else Times New Roman/serif) instead
# of fabricating a fake embedded font.
_FONT_PATH = _TEMPLATE_DIR / "fonts" / "report-serif.ttf"


class NoApprovedOutputsError(Exception):
    """Raised when a coverage has no enforcer-approved research to report on."""


def _load_font_base64() -> str | None:
    if not _FONT_PATH.exists():
        return None
    import base64

    return base64.b64encode(_FONT_PATH.read_bytes()).decode("ascii")


def _footnote_number(
    doc: str, section: str, quote: str, footnotes: dict[tuple[str, str, str], int]
) -> int:
    key = (doc.strip(), section.strip(), quote.strip())
    if key not in footnotes:
        footnotes[key] = len(footnotes) + 1
    return footnotes[key]


def _citations_to_placeholders(content: str, footnotes: dict[tuple[str, str, str], int]) -> str:
    def _replace(match: re.Match[str]) -> str:
        n = _footnote_number(match.group(1), match.group(2), match.group(3), footnotes)
        return f"@@CITE{n}@@"

    return _CITATION_PATTERN.sub(_replace, content)


def _placeholders_to_markers(escaped_text: str) -> str:
    return _PLACEHOLDER_RE.sub(
        r'<sup class="citation-ref"><a href="#cite-\1">[\1]</a></sup>', escaped_text
    )


def _render_table_block(lines: list[str]) -> str:
    rows = [
        [cell.strip() for cell in line.strip().strip("|").split("|")]
        for line in lines
        if not _TABLE_SEPARATOR_RE.match(line.strip())
    ]
    if not rows:
        return ""

    def _cell_html(cell: str) -> str:
        return _placeholders_to_markers(_html.escape(cell))

    header, *body = rows
    thead = "<tr>" + "".join(f"<th>{_cell_html(c)}</th>" for c in header) + "</tr>"
    tbody = "".join(
        "<tr>" + "".join(f"<td>{_cell_html(c)}</td>" for c in row) + "</tr>" for row in body
    )
    return f'<table class="data-table"><thead>{thead}</thead><tbody>{tbody}</tbody></table>'


def _render_body_html(content_with_placeholders: str) -> str:
    """Render agent-output body text (with `_citations_to_placeholders` already
    applied) into HTML: plain paragraphs, plus markdown pipe-tables rendered
    as real <table> elements so citations inside table cells still resolve.
    """
    blocks = re.split(r"\n\s*\n", content_with_placeholders.strip())
    parts: list[str] = []
    for block in blocks:
        lines = [line for line in block.splitlines() if line.strip()]
        if lines and all(_TABLE_LINE_RE.match(line) for line in lines):
            parts.append(_render_table_block(lines))
        else:
            escaped = _html.escape(block).replace("\n", "<br/>")
            parts.append(f"<p>{_placeholders_to_markers(escaped)}</p>")
    return "\n".join(parts)


def _render_notes_html(notes_content_html: str, footnotes: dict[tuple[str, str, str], int]) -> str:
    """Notes come from Tiptap's `editor.getHTML()` — already HTML restricted
    to Tiptap's own node schema, so citations are substituted directly into
    footnote markers without a second escaping pass (escaping already-HTML
    content here would double-escape every existing tag).
    """
    with_placeholders = _citations_to_placeholders(notes_content_html, footnotes)
    return _placeholders_to_markers(with_placeholders)


class ReportGenerator:
    def __init__(self) -> None:
        self._jinja_env = Environment(
            loader=FileSystemLoader(str(_TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )

    async def generate_coverage_report(
        self,
        db: AsyncSession,
        coverage_id: str,
        tenant_id: str,
        include_sections: list[str] | None = None,
    ) -> bytes:
        coverage = await db.get(Coverage, uuid.UUID(coverage_id))
        if coverage is None or coverage.tenant_id != uuid.UUID(tenant_id):
            raise NoApprovedOutputsError("Coverage not found")

        latest_by_type = await self._fetch_latest_approved_outputs(db, coverage.id, include_sections)
        notes = await self._fetch_notes(db, coverage.id)

        if not latest_by_type and notes is None:
            raise NoApprovedOutputsError("No approved research outputs found")

        kpi_rows = (
            (
                await db.execute(
                    select(KpiTimeseries)
                    .where(KpiTimeseries.coverage_id == coverage.id)
                    .order_by(KpiTimeseries.kpi_name, KpiTimeseries.period)
                )
            )
            .scalars()
            .all()
        )

        footnotes: dict[tuple[str, str, str], int] = {}
        sections = self._build_sections(latest_by_type, footnotes)
        notes_html = _render_notes_html(notes.content, footnotes) if notes and notes.content.strip() else None
        kpi_tables = self._build_kpi_tables(kpi_rows)
        citation_list = [
            {"number": n, "doc": doc, "section": section, "quote": quote}
            for (doc, section, quote), n in sorted(footnotes.items(), key=lambda kv: kv[1])
        ]

        html = self._build_html(coverage, sections, kpi_tables, citation_list, notes_html)
        # WeasyPrint's layout/rasterization is synchronous and CPU-bound
        # (~3-5s for a full report) — run it off the event loop so it
        # doesn't stall every other request this worker is handling.
        return await asyncio.to_thread(lambda: HTML(string=html, base_url=str(_TEMPLATE_DIR)).write_pdf())

    async def _fetch_latest_approved_outputs(
        self, db: AsyncSession, coverage_id: uuid.UUID, include_sections: list[str] | None
    ) -> dict[OutputTypeEnum, ResearchOutput]:
        stmt = (
            select(ResearchOutput)
            .where(
                ResearchOutput.coverage_id == coverage_id,
                ResearchOutput.approved_by_enforcer.is_(True),
            )
            .order_by(ResearchOutput.output_type, ResearchOutput.version.desc())
        )
        rows = (await db.execute(stmt)).scalars().all()

        latest_by_type: dict[OutputTypeEnum, ResearchOutput] = {}
        for row in rows:
            latest_by_type.setdefault(row.output_type, row)

        if include_sections:
            wanted = {OutputTypeEnum(s) for s in include_sections}
            latest_by_type = {k: v for k, v in latest_by_type.items() if k in wanted}

        return latest_by_type

    async def _fetch_notes(self, db: AsyncSession, coverage_id: uuid.UUID) -> CoverageNotes | None:
        return (
            await db.execute(select(CoverageNotes).where(CoverageNotes.coverage_id == coverage_id))
        ).scalar_one_or_none()

    def _build_sections(
        self,
        outputs_by_type: dict[OutputTypeEnum, ResearchOutput],
        footnotes: dict[tuple[str, str, str], int],
    ) -> list[dict[str, str]]:
        sections = []
        for output_type in _SECTION_ORDER:
            output = outputs_by_type.get(output_type)
            if output is None:
                continue
            with_placeholders = _citations_to_placeholders(output.content, footnotes)
            sections.append(
                {"title": _SECTION_TITLES[output_type], "body_html": _render_body_html(with_placeholders)}
            )
        return sections

    def _build_kpi_tables(self, kpi_rows: list[KpiTimeseries]) -> list[dict[str, Any]]:
        by_kpi: dict[str, list[KpiTimeseries]] = {}
        for row in kpi_rows:
            by_kpi.setdefault(row.kpi_name, []).append(row)

        tables = []
        for kpi_name, points in by_kpi.items():
            points.sort(key=lambda p: p.period)
            tables.append(
                {
                    "name": kpi_name,
                    "unit": points[0].unit,
                    "rows": [
                        {"period": p.period, "value": p.value, "restated": p.is_restated}
                        for p in points
                    ],
                }
            )
        return tables

    def _build_html(
        self,
        coverage: Coverage,
        sections: list[dict[str, str]],
        kpi_tables: list[dict[str, Any]],
        citations: list[dict[str, Any]],
        notes_html: str | None,
    ) -> str:
        template = self._jinja_env.get_template("report.html")
        return template.render(
            company_name=coverage.company_name,
            ticker=coverage.ticker,
            exchange=coverage.exchange,
            generated_date=datetime.now(timezone.utc).strftime("%B %d, %Y"),
            sections=sections,
            kpi_tables=kpi_tables,
            citations=citations,
            notes_html=notes_html,
            font_base64=_load_font_base64(),
        )
