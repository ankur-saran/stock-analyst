"""Unit tests for HierarchicalChunker.

A synthetic ParsedDocument with 3 sections of 20 paragraphs each stands in
for a real filing, plus one ExtractedTable, so we can check parent/child/table
structure, metadata completeness, and the token-budget tolerances without
needing a real PDF or Docling.
"""
from __future__ import annotations

import pytest

from rag.ingestion.chunkers.hierarchical import REQUIRED_METADATA_KEYS, Chunk, HierarchicalChunker
from rag.ingestion.parsers.pdf_parser import ParsedDocument, ParsedPage, TextBlock
from rag.ingestion.parsers.table_extractor import ExtractedTable, TableCell

SECTION_NAMES = ["business", "risk_factors", "mda"]
PARAGRAPHS_PER_SECTION = 20


def _make_paragraph(section: str, i: int) -> str:
    return (
        f"This is paragraph {i} of the {section} section. "
        f"It discusses relevant financial and operational details for item {i}. "
        f"Revenue increased significantly during this reporting period for item {i}."
    )


def _make_parsed_document() -> ParsedDocument:
    sections: dict[str, str] = {}
    pages: list[ParsedPage] = []
    for section in SECTION_NAMES:
        paragraphs = [_make_paragraph(section, i) for i in range(PARAGRAPHS_PER_SECTION)]
        sections[section] = "\n\n".join(paragraphs)
        page_number = len(pages) + 1
        pages.append(
            ParsedPage(
                page_number=page_number,
                text_blocks=[
                    TextBlock(
                        text=paragraphs[0],
                        page_number=page_number,
                        block_type="paragraph",
                        font_size=10.0,
                        bbox=(0.0, 0.0, 0.0, 0.0),
                    )
                ],
                raw_text=sections[section],
                text_coverage_pct=1.0,
                has_tables=False,
            )
        )
    return ParsedDocument(
        document_id="doc-1",
        file_name="synthetic-10k.pdf",
        pages=pages,
        total_pages=len(pages),
        overall_text_coverage=1.0,
        parser_used="pymupdf",
        sections=sections,
    )


def _make_table() -> ExtractedTable:
    cells = [
        TableCell(row=0, col=0, value="Metric", is_header=True),
        TableCell(row=0, col=1, value="2024", is_header=True),
        TableCell(row=1, col=0, value="Revenue", is_header=False),
        TableCell(row=1, col=1, value="1000", is_header=False),
    ]
    return ExtractedTable(
        page_number=1,
        table_index=0,
        caption="Revenue Table",
        section_name="business",
        cells=cells,
        column_headers=["Metric", "2024"],
        row_headers=["Revenue"],
        as_markdown="| Metric | 2024 |\n| --- | --- |\n| Revenue | 1000 |",
        as_json={
            "headers": ["Metric", "2024"],
            "rows": [{"label": "Revenue", "values": {"2024": "1000"}}],
        },
        document_id="doc-1",
        filing_type="10-K",
        period="FY2024",
    )


@pytest.fixture()
def chunks() -> list[Chunk]:
    parsed_doc = _make_parsed_document()
    tables = [_make_table()]
    chunker = HierarchicalChunker()
    return chunker.chunk_document(
        parsed_doc, tables, tenant_id="tenant-a", coverage_id="coverage-1"
    )


# ── Test 1: chunk types ───────────────────────────────────────────────────────


def test_chunk_types_are_valid(chunks: list[Chunk]) -> None:
    assert chunks
    assert {c.chunk_type for c in chunks} <= {"parent", "child", "table"}
    assert {"parent", "child", "table"} <= {c.chunk_type for c in chunks}


# ── Test 2: child → parent linkage ────────────────────────────────────────────


def test_every_child_has_a_valid_parent(chunks: list[Chunk]) -> None:
    parent_ids = {c.chunk_id for c in chunks if c.chunk_type == "parent"}
    children = [c for c in chunks if c.chunk_type == "child"]
    assert children
    for child in children:
        assert child.parent_chunk_id in parent_ids
        assert child.metadata["parent_chunk_id"] == child.parent_chunk_id


# ── Test 3: required metadata keys ────────────────────────────────────────────


def test_every_chunk_has_required_metadata_keys(chunks: list[Chunk]) -> None:
    for chunk in chunks:
        for key in REQUIRED_METADATA_KEYS:
            assert key in chunk.metadata, f"{chunk.chunk_type} chunk missing '{key}'"


# ── Test 4 & 5: token budgets ──────────────────────────────────────────────────


def test_parent_chunks_within_token_tolerance(chunks: list[Chunk]) -> None:
    parents = [c for c in chunks if c.chunk_type == "parent"]
    assert parents
    for parent in parents:
        assert parent.metadata["token_estimate"] <= 2200


def test_child_chunks_within_token_tolerance(chunks: list[Chunk]) -> None:
    children = [c for c in chunks if c.chunk_type == "child"]
    assert children
    for child in children:
        assert child.metadata["token_estimate"] <= 240


# ── Test 6: no empty content ──────────────────────────────────────────────────


def test_no_chunk_has_empty_content(chunks: list[Chunk]) -> None:
    for chunk in chunks:
        assert chunk.content.strip() != ""


# ── Test 7: table chunk content ───────────────────────────────────────────────


def test_table_chunks_start_with_table_prefix(chunks: list[Chunk]) -> None:
    tables = [c for c in chunks if c.chunk_type == "table"]
    assert tables
    for table_chunk in tables:
        assert table_chunk.content.startswith("TABLE:")


# ── Test 8: many children per parent ──────────────────────────────────────────


def test_more_children_than_parents(chunks: list[Chunk]) -> None:
    parents = [c for c in chunks if c.chunk_type == "parent"]
    children = [c for c in chunks if c.chunk_type == "child"]
    assert len(children) > len(parents)
