"""Structured table extraction from SEC filings using Docling.

Docling detects table geometry (rows/cols/headers) far more reliably than
PyMuPDF's text blocks, but it has no notion of the filing's section
structure. We cross-reference each table's page number against the section
map already built by :class:`~rag.ingestion.parsers.pdf_parser.PDFParser` to
tag which section (MD&A, financial statements, ...) a table belongs to, and
use PDFParser's text blocks to guess a caption from the text sitting just
above the table on the page.

Docling's converter is synchronous and CPU-heavy; ``extract_tables_async``
wraps it in ``asyncio.to_thread`` so callers on the event loop don't block.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rag.ingestion.parsers.pdf_parser import _SECTION_PATTERNS, ParsedDocument

_CAPTION_MAX_LEN = 150


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class TableCell:
    row: int
    col: int
    value: str
    is_header: bool


@dataclass
class ExtractedTable:
    page_number: int
    table_index: int
    caption: str | None
    section_name: str
    cells: list[TableCell]
    column_headers: list[str]
    row_headers: list[str]
    as_markdown: str
    as_json: dict[str, Any]
    document_id: str
    filing_type: str
    period: str


class TableExtractor:
    def extract_tables(
        self,
        file_path: Path,
        parsed_document: ParsedDocument,
        document_id: str,
        filing_type: str,
        period: str,
    ) -> list[ExtractedTable]:
        from docling.document_converter import DocumentConverter

        converter = DocumentConverter()
        result = converter.convert(str(file_path))

        page_sections = self._page_sections(parsed_document)
        page_table_counts: dict[int, int] = {}
        tables: list[ExtractedTable] = []

        for table in result.document.tables:
            page_number = self._page_number(table)
            table_index = page_table_counts.get(page_number, 0)
            page_table_counts[page_number] = table_index + 1

            cells = self._cells_from_table(table)
            column_headers, row_headers = self._derive_headers(cells)

            tables.append(
                ExtractedTable(
                    page_number=page_number,
                    table_index=table_index,
                    caption=self._infer_caption(table, parsed_document),
                    section_name=page_sections.get(page_number, "unknown"),
                    cells=cells,
                    column_headers=column_headers,
                    row_headers=row_headers,
                    as_markdown=self._table_to_markdown(cells, column_headers),
                    as_json=self._table_to_json(cells, column_headers, row_headers),
                    document_id=document_id,
                    filing_type=filing_type,
                    period=period,
                )
            )

        return tables

    async def extract_tables_async(
        self,
        file_path: Path,
        parsed_document: ParsedDocument,
        document_id: str,
        filing_type: str,
        period: str,
    ) -> list[ExtractedTable]:
        return await asyncio.to_thread(
            self.extract_tables, file_path, parsed_document, document_id, filing_type, period
        )

    # ── Caption detection ─────────────────────────────────────────────────────

    def _infer_caption(self, table: Any, parsed_document: ParsedDocument) -> str | None:
        page_number = self._page_number(table)
        page = next((p for p in parsed_document.pages if p.page_number == page_number), None)
        if page is None:
            return None

        cell_texts = {c.value for c in self._cells_from_table(table)}
        candidates = [
            block.text.strip()
            for block in page.text_blocks
            if block.text.strip() and block.text.strip() not in cell_texts
        ]
        if not candidates:
            return None

        candidate = candidates[-1]
        if len(candidate) < _CAPTION_MAX_LEN and not candidate.endswith("."):
            return candidate
        return None

    # ── Docling table → our schema ───────────────────────────────────────────

    def _page_number(self, table: Any) -> int:
        prov = getattr(table, "prov", None) or []
        if prov:
            return getattr(prov[0], "page_no", 1)
        return 1

    def _cells_from_table(self, table: Any) -> list[TableCell]:
        table_cells = getattr(table.data, "table_cells", [])
        cells: list[TableCell] = []
        for tc in table_cells:
            is_header = bool(getattr(tc, "column_header", False)) or bool(
                getattr(tc, "row_header", False)
            )
            cells.append(
                TableCell(
                    row=tc.start_row_offset_idx,
                    col=tc.start_col_offset_idx,
                    value=str(tc.text).strip(),
                    is_header=is_header,
                )
            )
        return cells

    def _derive_headers(self, cells: list[TableCell]) -> tuple[list[str], list[str]]:
        if not cells:
            return [], []

        max_col = max(c.col for c in cells)
        max_row = max(c.row for c in cells)

        column_headers = [""] * (max_col + 1)
        for c in cells:
            if c.row == 0:
                column_headers[c.col] = c.value

        row_headers: list[str] = []
        for row_idx in range(1, max_row + 1):
            label = next((c.value for c in cells if c.row == row_idx and c.col == 0), "")
            row_headers.append(label)

        return column_headers, row_headers

    # ── Section cross-reference ──────────────────────────────────────────────

    def _page_sections(self, parsed_document: ParsedDocument) -> dict[int, str]:
        mapping: dict[int, str] = {}
        current_section = "cover"

        for page in parsed_document.pages:
            for block in page.text_blocks:
                matched = next(
                    (name for name, pattern in _SECTION_PATTERNS if pattern.search(block.text)),
                    None,
                )
                if matched is not None:
                    current_section = matched
            mapping[page.page_number] = current_section

        return mapping

    # ── Rendering ─────────────────────────────────────────────────────────────

    def _build_grid(self, cells: list[TableCell]) -> list[list[str]]:
        if not cells:
            return []
        max_row = max(c.row for c in cells)
        max_col = max(c.col for c in cells)
        grid = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
        for c in cells:
            grid[c.row][c.col] = c.value
        return grid

    def _table_to_markdown(self, cells: list[TableCell], col_headers: list[str]) -> str:
        grid = self._build_grid(cells)
        if not grid:
            return ""

        header = col_headers if any(col_headers) else grid[0]
        data_rows = grid[1:]

        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in data_rows:
            padded = (row + [""] * len(header))[: len(header)]
            lines.append("| " + " | ".join(padded) + " |")

        return "\n".join(lines)

    def _table_to_json(
        self, cells: list[TableCell], col_headers: list[str], row_headers: list[str]
    ) -> dict[str, Any]:
        grid = self._build_grid(cells)
        if not grid:
            return {"headers": [], "rows": []}

        headers = col_headers if any(col_headers) else grid[0]
        data_rows = grid[1:]

        rows = []
        for i, row in enumerate(data_rows):
            label = row_headers[i] if i < len(row_headers) else (row[0] if row else "")
            values = {
                headers[col_idx]: row[col_idx]
                for col_idx in range(1, len(headers))
                if col_idx < len(row)
            }
            rows.append({"label": label, "values": values})

        return {"headers": headers, "rows": rows}
