"""Unit tests for TableExtractor.

Docling is a heavy optional dependency imported lazily inside
``TableExtractor.extract_tables``. We fake it out via ``sys.modules``
injection so these tests exercise our mapping/rendering logic without
requiring docling (and its ML backends) to be installed.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from reportlab.pdfgen import canvas

from rag.ingestion.parsers.pdf_parser import PDFParser
from rag.ingestion.parsers.table_extractor import ExtractedTable, TableExtractor

CAPTION_TEXT = "Revenue by Segment (in millions)"


# ── Fake docling objects ──────────────────────────────────────────────────────


class _FakeProv:
    def __init__(self, page_no: int) -> None:
        self.page_no = page_no


class _FakeCell:
    def __init__(
        self,
        row: int,
        col: int,
        text: str,
        *,
        column_header: bool = False,
        row_header: bool = False,
    ) -> None:
        self.start_row_offset_idx = row
        self.start_col_offset_idx = col
        self.text = text
        self.column_header = column_header
        self.row_header = row_header


class _FakeTableData:
    def __init__(self, cells: list[_FakeCell]) -> None:
        self.table_cells = cells


class _FakeTable:
    def __init__(self, cells: list[_FakeCell], page_no: int) -> None:
        self.data = _FakeTableData(cells)
        self.prov = [_FakeProv(page_no)]


class _FakeDocument:
    def __init__(self, tables: list[_FakeTable]) -> None:
        self.tables = tables


class _FakeResult:
    def __init__(self, document: _FakeDocument) -> None:
        self.document = document


def _install_fake_docling(monkeypatch: pytest.MonkeyPatch, tables: list[_FakeTable]) -> None:
    fake_converter_module = types.ModuleType("docling.document_converter")

    class FakeDocumentConverter:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def convert(self, path: str) -> _FakeResult:
            return _FakeResult(_FakeDocument(tables))

    fake_converter_module.DocumentConverter = FakeDocumentConverter  # type: ignore[attr-defined]

    fake_docling_pkg = types.ModuleType("docling")
    fake_docling_pkg.document_converter = fake_converter_module  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "docling", fake_docling_pkg)
    monkeypatch.setitem(sys.modules, "docling.document_converter", fake_converter_module)


def _income_statement_cells() -> list[_FakeCell]:
    return [
        _FakeCell(0, 0, "Metric", column_header=True),
        _FakeCell(0, 1, "2024", column_header=True),
        _FakeCell(0, 2, "2023", column_header=True),
        _FakeCell(1, 0, "Revenue", row_header=True),
        _FakeCell(1, 1, "1000"),
        _FakeCell(1, 2, "900"),
        _FakeCell(2, 0, "Net income", row_header=True),
        _FakeCell(2, 1, "200"),
        _FakeCell(2, 2, "150"),
    ]


def _make_pdf_with_caption(path: Path) -> Path:
    """A page dense enough that PyMuPDF's coverage stays above the fallback
    threshold (the Unstructured.io fallback isn't installed in test envs),
    with the caption as the last text block so it stays isolated/detectable.
    """
    c = canvas.Canvas(str(path), pagesize=(612, 792))
    c.setFont("Helvetica-Bold", 14)
    c.drawString(20, 760, "Income Statement")

    c.setFont("Helvetica", 9)
    line = "The Company reports consolidated results across all operating segments each period. "
    y = 730
    while y > 100:
        c.drawString(20, y, line)
        y -= 10

    c.setFont("Helvetica", 10)
    c.drawString(20, 80, CAPTION_TEXT)

    c.showPage()
    c.save()
    return path


@pytest.fixture()
def extracted_tables(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> list[ExtractedTable]:
    pdf_path = _make_pdf_with_caption(tmp_path / "filing.pdf")
    fake_table = _FakeTable(_income_statement_cells(), page_no=1)
    _install_fake_docling(monkeypatch, [fake_table])

    parsed_document = PDFParser().parse(pdf_path, document_id="doc-1", file_name="filing.pdf")

    extractor = TableExtractor()
    return extractor.extract_tables(
        pdf_path,
        parsed_document,
        document_id="doc-1",
        filing_type="10-K",
        period="FY2024",
    )


# ── Test 1: column headers ────────────────────────────────────────────────────


def test_extracts_table_with_correct_column_headers(
    extracted_tables: list[ExtractedTable],
) -> None:
    assert len(extracted_tables) == 1
    table = extracted_tables[0]

    assert table.column_headers == ["Metric", "2024", "2023"]
    assert table.row_headers == ["Revenue", "Net income"]
    assert table.page_number == 1
    assert table.table_index == 0


# ── Test 2: markdown rendering ────────────────────────────────────────────────


def test_as_markdown_is_valid_pipe_delimited(extracted_tables: list[ExtractedTable]) -> None:
    table = extracted_tables[0]
    lines = table.as_markdown.splitlines()

    assert lines[0] == "| Metric | 2024 | 2023 |"
    assert lines[1] == "| --- | --- | --- |"
    assert "| Revenue | 1000 | 900 |" in lines
    assert "| Net income | 200 | 150 |" in lines


# ── Test 3: JSON structure ────────────────────────────────────────────────────


def test_as_json_has_correct_structure(extracted_tables: list[ExtractedTable]) -> None:
    table = extracted_tables[0]

    assert table.as_json["headers"] == ["Metric", "2024", "2023"]
    labels = [row["label"] for row in table.as_json["rows"]]
    assert "Revenue" in labels

    revenue_row = next(r for r in table.as_json["rows"] if r["label"] == "Revenue")
    assert revenue_row["values"] == {"2024": "1000", "2023": "900"}


# ── Test 4: caption detection ─────────────────────────────────────────────────


def test_caption_detected_from_text_above_table(extracted_tables: list[ExtractedTable]) -> None:
    table = extracted_tables[0]
    assert table.caption == CAPTION_TEXT
