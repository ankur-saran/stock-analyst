"""Unit tests for PDFParser using small synthetic PDFs built with reportlab."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from reportlab.pdfgen import canvas

from rag.ingestion.parsers.pdf_parser import ParsedPage, PDFParser, TextBlock


def _make_pdf(path: Path, draw) -> Path:
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    draw(c)
    c.showPage()
    c.save()
    return path


# ── Test 1: dense text page → high coverage via PyMuPDF ──────────────────────


def test_dense_text_page_parsed_with_pymupdf_has_high_coverage(tmp_path: Path) -> None:
    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica", 9)
        line = "The quick brown fox jumps over the lazy dog near the riverbank today. "
        y = 780
        while y > 20:
            c.drawString(20, y, line)
            y -= 10

    pdf_path = _make_pdf(tmp_path / "dense.pdf", draw)

    parser = PDFParser()
    doc = parser.parse(pdf_path, document_id="doc-1", file_name="dense.pdf")

    assert doc.parser_used == "pymupdf"
    assert doc.pages[0].text_coverage_pct > 0.8


# ── Test 2: blank page → falls back to Unstructured ──────────────────────────


def test_blank_page_falls_back_to_unstructured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = _make_pdf(tmp_path / "blank.pdf", draw=lambda c: None)

    dummy_pages = [
        ParsedPage(
            page_number=1,
            text_blocks=[],
            raw_text="ocr recovered text",
            text_coverage_pct=1.0,
            has_tables=False,
        )
    ]
    fallback = MagicMock(return_value=dummy_pages)
    monkeypatch.setattr(PDFParser, "_parse_with_unstructured", fallback)

    parser = PDFParser()
    doc = parser.parse(pdf_path, document_id="doc-2", file_name="blank.pdf")

    fallback.assert_called_once()
    assert doc.parser_used == "unstructured"
    assert doc.pages == dummy_pages


# ── Test 3: large font → heading classification ──────────────────────────────


def test_large_font_block_classified_as_heading(tmp_path: Path) -> None:
    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 24)
        c.drawString(20, 760, "SECTION TITLE")

        c.setFont("Helvetica", 9)
        line = "This is ordinary body paragraph text used to fill the page densely. "
        y = 700
        while y > 20:
            c.drawString(20, y, line)
            y -= 10

    pdf_path = _make_pdf(tmp_path / "heading.pdf", draw)

    parser = PDFParser()
    doc = parser.parse(pdf_path, document_id="doc-3", file_name="heading.pdf")

    blocks = doc.pages[0].text_blocks
    heading_blocks = [b for b in blocks if b.block_type == "heading"]
    paragraph_blocks = [b for b in blocks if b.block_type == "paragraph"]

    assert any("SECTION TITLE" in b.text for b in heading_blocks)
    assert paragraph_blocks


# ── Test 4: section detection ────────────────────────────────────────────────


def test_risk_factors_section_detected(tmp_path: Path) -> None:
    def draw(c: canvas.Canvas) -> None:
        c.setFont("Helvetica-Bold", 20)
        c.drawString(20, 760, "ITEM 1A. RISK FACTORS")

        c.setFont("Helvetica", 9)
        line = "Our business is subject to a number of material risks that could hurt us. "
        y = 700
        while y > 20:
            c.drawString(20, y, line)
            y -= 10

    pdf_path = _make_pdf(tmp_path / "risk_factors.pdf", draw)

    parser = PDFParser()
    doc = parser.parse(pdf_path, document_id="doc-4", file_name="risk_factors.pdf")

    assert "risk_factors" in doc.sections
    assert "material risks" in doc.sections["risk_factors"]
