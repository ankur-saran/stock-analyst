"""Two-stage PDF parser: PyMuPDF first, falling back to Unstructured.io.

PyMuPDF is fast and handles normal (digitally-authored) filings well. When a
page's extractable text is too sparse — typically a scanned page — we
re-parse the whole document with Unstructured's hi_res (OCR-backed) strategy.
Unstructured is a heavy optional dependency, so it's imported lazily.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import fitz

LOW_COVERAGE_THRESHOLD = 0.50

_HEADING_FONT_RATIO = 1.15
_HEADING_FONT_DELTA = 2.0

_LIST_ITEM_RE = re.compile(r"^\s*([\-\*•●]|\d+[.)])\s+")
_CAPTION_RE = re.compile(r"^\s*(figure|table|exhibit)\s*\d*[:.]", re.IGNORECASE)
_GRID_CHARS_RE = re.compile(r"\t.*\t|│")

_SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("business", re.compile(r"item\s+1\.?\s+business", re.IGNORECASE)),
    ("risk_factors", re.compile(r"item\s+1a\.?\s+risk\s+factors", re.IGNORECASE)),
    ("mda", re.compile(
        r"item\s+7\.?\s+management.?s\s+discussion\s+and\s+analysis", re.IGNORECASE
    )),
    ("financial_statements", re.compile(
        r"item\s+8\.?\s+financial\s+statements", re.IGNORECASE
    )),
    ("notes_to_financials", re.compile(
        r"notes?\s+to\s+(?:the\s+)?(?:consolidated\s+)?financial\s+statements",
        re.IGNORECASE,
    )),
    ("controls", re.compile(
        r"item\s+9a\.?\s+controls\s+and\s+procedures", re.IGNORECASE
    )),
    ("exhibits", re.compile(r"item\s+15\.?\s+exhibits", re.IGNORECASE)),
]


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class TextBlock:
    text: str
    page_number: int
    block_type: str
    font_size: float
    bbox: tuple[float, float, float, float]


@dataclass
class ParsedPage:
    page_number: int
    text_blocks: list[TextBlock]
    raw_text: str
    text_coverage_pct: float
    has_tables: bool


@dataclass
class ParsedDocument:
    document_id: str
    file_name: str
    pages: list[ParsedPage]
    total_pages: int
    overall_text_coverage: float
    parser_used: str
    sections: dict[str, str] = field(default_factory=dict)


class PDFParser:
    def parse(self, file_path: Path, document_id: str, file_name: str) -> ParsedDocument:
        pages = self._parse_with_pymupdf(file_path)
        overall_coverage = self._overall_coverage(pages)
        parser_used = "pymupdf"

        if overall_coverage < LOW_COVERAGE_THRESHOLD:
            pages = self._parse_with_unstructured(file_path)
            overall_coverage = self._overall_coverage(pages)
            parser_used = "unstructured"

        return ParsedDocument(
            document_id=document_id,
            file_name=file_name,
            pages=pages,
            total_pages=len(pages),
            overall_text_coverage=overall_coverage,
            parser_used=parser_used,
            sections=self._detect_sections(pages),
        )

    @staticmethod
    def _overall_coverage(pages: list[ParsedPage]) -> float:
        if not pages:
            return 0.0
        return sum(p.text_coverage_pct for p in pages) / len(pages)

    # ── PyMuPDF ───────────────────────────────────────────────────────────────

    def _parse_with_pymupdf(self, file_path: Path) -> list[ParsedPage]:
        pages: list[ParsedPage] = []
        with fitz.open(file_path) as doc:
            for page_index in range(doc.page_count):
                page = doc[page_index]
                raw_dict = page.get_text("dict")
                blocks_raw = [b for b in raw_dict.get("blocks", []) if b.get("type") == 0]

                font_sizes: list[float] = []
                extracted = []
                for block in blocks_raw:
                    text, size = self._block_text_and_font(block)
                    if not text.strip():
                        continue
                    font_sizes.append(size)
                    extracted.append((block, text, size))

                text_blocks: list[TextBlock] = []
                for block, text, size in extracted:
                    block_type = self._classify_block(text, size, font_sizes)
                    text_blocks.append(
                        TextBlock(
                            text=text,
                            page_number=page_index + 1,
                            block_type=block_type,
                            font_size=size,
                            bbox=tuple(block.get("bbox", (0.0, 0.0, 0.0, 0.0))),
                        )
                    )

                raw_text = "\n".join(tb.text for tb in text_blocks)
                page_area = max(page.rect.width * page.rect.height, 1.0)
                text_coverage_pct = len(raw_text) / (page_area / 100)
                has_tables = any(_GRID_CHARS_RE.search(tb.text) for tb in text_blocks)

                pages.append(
                    ParsedPage(
                        page_number=page_index + 1,
                        text_blocks=text_blocks,
                        raw_text=raw_text,
                        text_coverage_pct=text_coverage_pct,
                        has_tables=has_tables,
                    )
                )
        return pages

    @staticmethod
    def _block_text_and_font(block: dict[str, Any]) -> tuple[str, float]:
        lines_text: list[str] = []
        sizes: list[float] = []
        for line in block.get("lines", []):
            spans = line.get("spans", [])
            lines_text.append("".join(span.get("text", "") for span in spans))
            sizes.extend(span.get("size", 0.0) for span in spans)
        text = "\n".join(lines_text)
        font_size = max(sizes) if sizes else 0.0
        return text, font_size

    @staticmethod
    def _classify_block(text: str, font_size: float, page_font_sizes: list[float]) -> str:
        stripped = text.strip()

        if _LIST_ITEM_RE.match(stripped):
            return "list_item"
        if _CAPTION_RE.match(stripped):
            return "caption"

        if page_font_sizes:
            median_size = statistics.median(page_font_sizes)
            max_size = max(page_font_sizes)
            is_largest = font_size >= max_size - 0.5
            is_notably_larger = font_size > median_size * _HEADING_FONT_RATIO or (
                font_size - median_size
            ) > _HEADING_FONT_DELTA
            if is_largest and is_notably_larger:
                return "heading"

        return "paragraph"

    # ── Unstructured.io fallback ──────────────────────────────────────────────

    def _parse_with_unstructured(self, file_path: Path) -> list[ParsedPage]:
        from unstructured.partition.pdf import partition_pdf

        elements = partition_pdf(filename=str(file_path), strategy="hi_res")

        pages_by_number: dict[int, list[TextBlock]] = {}
        type_map = {
            "Title": "heading",
            "Header": "heading",
            "ListItem": "list_item",
            "FigureCaption": "caption",
            "Caption": "caption",
        }

        for element in elements:
            page_number = getattr(element.metadata, "page_number", None) or 1
            block_type = type_map.get(type(element).__name__, "paragraph")
            coords = getattr(element.metadata, "coordinates", None)
            bbox = (0.0, 0.0, 0.0, 0.0)
            if coords is not None and getattr(coords, "points", None):
                xs = [p[0] for p in coords.points]
                ys = [p[1] for p in coords.points]
                bbox = (min(xs), min(ys), max(xs), max(ys))

            pages_by_number.setdefault(page_number, []).append(
                TextBlock(
                    text=str(element),
                    page_number=page_number,
                    block_type=block_type,
                    font_size=0.0,
                    bbox=bbox,
                )
            )

        pages: list[ParsedPage] = []
        for page_number in sorted(pages_by_number):
            blocks = pages_by_number[page_number]
            raw_text = "\n".join(b.text for b in blocks)
            has_tables = any(_GRID_CHARS_RE.search(b.text) for b in blocks)
            pages.append(
                ParsedPage(
                    page_number=page_number,
                    text_blocks=blocks,
                    raw_text=raw_text,
                    text_coverage_pct=1.0 if raw_text else 0.0,
                    has_tables=has_tables,
                )
            )
        return pages

    # ── Section detection ─────────────────────────────────────────────────────

    def _detect_sections(self, pages: list[ParsedPage]) -> dict[str, str]:
        sections: dict[str, list[str]] = {}
        current_section = "cover"

        for page in pages:
            for block in page.text_blocks:
                matched_section = next(
                    (name for name, pattern in _SECTION_PATTERNS if pattern.search(block.text)),
                    None,
                )
                if matched_section is not None:
                    current_section = matched_section
                sections.setdefault(current_section, []).append(block.text)

        return {name: "\n".join(texts) for name, texts in sections.items() if texts}
