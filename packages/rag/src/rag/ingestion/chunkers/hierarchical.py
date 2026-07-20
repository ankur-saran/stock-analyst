"""Hierarchical parent/child chunker for indexed filing sections.

Parent chunks (~2000 tokens) preserve full section context for hydration;
child chunks (~200 tokens, sentence-bounded, overlapping) are the units that
actually get embedded and searched. Table chunks are one-per-extracted-table
so the Citation Enforcer can BM25-match exact figures.

``ParsedDocument.sections`` carries section text but not ``filing_type``,
``period``, or a display name (those are caller-supplied downstream metadata,
same pattern as ``TableExtractor.extract_tables``), so ``chunk_document``
takes them as optional keyword arguments and falls back to the first table's
values / the parsed document's file name when omitted.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from rag.ingestion.parsers.pdf_parser import _SECTION_PATTERNS, ParsedDocument
from rag.ingestion.parsers.table_extractor import ExtractedTable

_PARAGRAPH_SPLIT_RE = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.\n])\s+")
_TOKEN_ESTIMATE_FACTOR = 1.3

REQUIRED_METADATA_KEYS = (
    "document_id",
    "document_name",
    "filing_type",
    "period",
    "page_number",
    "section_name",
    "chunk_type",
    "parent_chunk_id",
    "tenant_id",
    "coverage_id",
    "char_start",
    "char_end",
    "token_estimate",
)


# ── Data classes ──────────────────────────────────────────────────────────────


@dataclass
class Chunk:
    chunk_id: str
    content: str
    chunk_type: str
    parent_chunk_id: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


class HierarchicalChunker:
    def __init__(
        self,
        parent_max_tokens: int = 2000,
        child_max_tokens: int = 200,
        child_overlap_tokens: int = 20,
    ) -> None:
        self.parent_max_tokens = parent_max_tokens
        self.child_max_tokens = child_max_tokens
        self.child_overlap_tokens = child_overlap_tokens

    # ── Top-level entry point ────────────────────────────────────────────────

    def chunk_document(
        self,
        parsed_doc: ParsedDocument,
        tables: list[ExtractedTable],
        tenant_id: str,
        coverage_id: str,
        *,
        filing_type: str | None = None,
        period: str | None = None,
        document_name: str | None = None,
    ) -> list[Chunk]:
        document_name = document_name or parsed_doc.file_name
        filing_type = filing_type or (tables[0].filing_type if tables else "unknown")
        period = period or (tables[0].period if tables else "unknown")

        section_first_page = self._section_first_pages(parsed_doc)
        tables_by_section: dict[str, list[ExtractedTable]] = {}
        for table in tables:
            tables_by_section.setdefault(table.section_name, []).append(table)

        chunks: list[Chunk] = []
        global_offset = 0
        for section_name, text in parsed_doc.sections.items():
            if text.strip():
                base_metadata = {
                    "document_id": parsed_doc.document_id,
                    "document_name": document_name,
                    "filing_type": filing_type,
                    "period": period,
                    "section_name": section_name,
                    "tenant_id": tenant_id,
                    "coverage_id": coverage_id,
                    "page_number": section_first_page.get(section_name, 1),
                }
                parents = self._split_into_parent_chunks(
                    section_name, text, base_metadata, global_offset
                )
                for parent in parents:
                    chunks.append(parent)
                    chunks.extend(self._split_into_child_chunks(parent))

            for table in tables_by_section.pop(section_name, []):
                chunks.append(
                    self._create_table_chunk(
                        table,
                        {
                            "document_name": document_name,
                            "tenant_id": tenant_id,
                            "coverage_id": coverage_id,
                        },
                    )
                )
            global_offset += len(text) + 2  # "\n\n" join between sections

        # Tables whose section didn't match any parsed section text.
        for leftover in tables_by_section.values():
            for table in leftover:
                chunks.append(
                    self._create_table_chunk(
                        table,
                        {
                            "document_name": document_name,
                            "tenant_id": tenant_id,
                            "coverage_id": coverage_id,
                        },
                    )
                )

        return chunks

    # ── Parent chunks ─────────────────────────────────────────────────────────

    def _split_into_parent_chunks(
        self,
        section_name: str,
        text: str,
        base_metadata: dict[str, Any],
        section_char_offset: int = 0,
    ) -> list[Chunk]:
        paragraphs = [p for p in _PARAGRAPH_SPLIT_RE.split(text) if p.strip()]
        if not paragraphs:
            return []
        offsets = self._locate_offsets(text, paragraphs)

        parents: list[Chunk] = []
        group: list[str] = []
        group_tokens = 0
        group_start: int | None = None
        group_end = 0

        def flush() -> None:
            nonlocal group, group_tokens, group_start, group_end
            if not group:
                return
            content = "\n\n".join(group)
            parents.append(
                self._make_chunk(
                    content=content,
                    chunk_type="parent",
                    parent_chunk_id=None,
                    base_metadata=base_metadata,
                    char_start=section_char_offset + (group_start or 0),
                    char_end=section_char_offset + group_end,
                )
            )
            group = []
            group_tokens = 0
            group_start = None

        for paragraph, (start, end) in zip(paragraphs, offsets):
            para_tokens = self._token_estimate(paragraph)
            if group and group_tokens + para_tokens > self.parent_max_tokens:
                flush()
            if group_start is None:
                group_start = start
            group.append(paragraph)
            group_tokens += para_tokens
            group_end = end
        flush()

        return parents

    # ── Child chunks ──────────────────────────────────────────────────────────

    def _split_into_child_chunks(self, parent: Chunk) -> list[Chunk]:
        sentences = [s for s in _SENTENCE_SPLIT_RE.split(parent.content) if s.strip()]
        if not sentences:
            return []
        offsets = self._locate_offsets(parent.content, sentences)
        sentence_tokens = [self._token_estimate(s) for s in sentences]
        parent_char_start = parent.metadata["char_start"]

        children: list[Chunk] = []
        n = len(sentences)
        idx = 0
        while idx < n:
            start_idx = idx
            group_tokens = 0
            while idx < n and (
                idx == start_idx or group_tokens + sentence_tokens[idx] <= self.child_max_tokens
            ):
                group_tokens += sentence_tokens[idx]
                idx += 1

            content = " ".join(sentences[start_idx:idx])
            char_start = parent_char_start + offsets[start_idx][0]
            char_end = parent_char_start + offsets[idx - 1][1]
            children.append(
                self._make_chunk(
                    content=content,
                    chunk_type="child",
                    parent_chunk_id=parent.chunk_id,
                    base_metadata=parent.metadata,
                    char_start=char_start,
                    char_end=char_end,
                )
            )

            if idx >= n:
                break

            # Step back over trailing sentences worth ~child_overlap_tokens
            # so the next child overlaps with this one; always advance past
            # start_idx so the loop makes forward progress.
            back = idx - 1
            overlap_tokens = 0
            while back > start_idx and overlap_tokens < self.child_overlap_tokens:
                overlap_tokens += sentence_tokens[back]
                back -= 1
            idx = max(back + 1, start_idx + 1)

        return children

    # ── Table chunks ──────────────────────────────────────────────────────────

    def _create_table_chunk(
        self, table: ExtractedTable, base_metadata: dict[str, Any]
    ) -> Chunk:
        content = (
            f"TABLE: {table.caption or 'Untitled'}\n\n"
            f"{table.as_markdown}\n\nJSON:\n{json.dumps(table.as_json)}"
        )
        metadata = {
            **base_metadata,
            "document_id": table.document_id,
            "filing_type": table.filing_type,
            "period": table.period,
            "page_number": table.page_number,
            "section_name": table.section_name,
            "chunk_type": "table",
            "parent_chunk_id": None,
            "char_start": 0,
            "char_end": len(content),
            "token_estimate": self._token_estimate(content),
        }
        return Chunk(
            chunk_id=str(uuid4()),
            content=content,
            chunk_type="table",
            parent_chunk_id=None,
            metadata=metadata,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _make_chunk(
        self,
        content: str,
        chunk_type: str,
        parent_chunk_id: str | None,
        base_metadata: dict[str, Any],
        char_start: int,
        char_end: int,
    ) -> Chunk:
        metadata = {
            **base_metadata,
            "chunk_type": chunk_type,
            "parent_chunk_id": parent_chunk_id,
            "char_start": char_start,
            "char_end": char_end,
            "token_estimate": self._token_estimate(content),
        }
        return Chunk(
            chunk_id=str(uuid4()),
            content=content,
            chunk_type=chunk_type,
            parent_chunk_id=parent_chunk_id,
            metadata=metadata,
        )

    @staticmethod
    def _locate_offsets(text: str, pieces: list[str]) -> list[tuple[int, int]]:
        offsets: list[tuple[int, int]] = []
        cursor = 0
        for piece in pieces:
            start = text.find(piece, cursor)
            if start == -1:
                start = cursor
            end = start + len(piece)
            offsets.append((start, end))
            cursor = end
        return offsets

    @staticmethod
    def _token_estimate(text: str) -> int:
        return int(len(text.split()) * _TOKEN_ESTIMATE_FACTOR)

    @staticmethod
    def _section_first_pages(parsed_doc: ParsedDocument) -> dict[str, int]:
        first_pages: dict[str, int] = {}
        current_section = "cover"
        for page in parsed_doc.pages:
            for block in page.text_blocks:
                matched = next(
                    (name for name, pattern in _SECTION_PATTERNS if pattern.search(block.text)),
                    None,
                )
                if matched is not None:
                    current_section = matched
            first_pages.setdefault(current_section, page.page_number)
        return first_pages
