"""Renders the synthetic fixture content into small, real PDFs.

Uses reportlab (already a test dependency of ``packages/rag``, see
``tests/unit/test_pdf_parser.py``) so ``rag.ingestion.parsers.pdf_parser.PDFParser``
can parse these exactly like it parses a real filing -- no shortcuts or mocked
parsing path for the eval fixtures.

Each fixture document gets its own page sized to exactly fit its content
(rather than a fixed Letter page) so ``PDFParser``'s text-coverage-per-page
check stays comfortably above the 50% threshold regardless of whether a
given fixture is a full multi-section 10-K or a single-paragraph 10-Q --
that ratio is what decides whether PyMuPDF's output is trusted or the parser
falls back to the (unavailable in this environment) Unstructured/OCR path.
"""
from __future__ import annotations

from pathlib import Path

from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from eval.fixtures.fixture_content import FIXTURE_DOCUMENTS, Section

_PAGE_WIDTH = 612.0
_MARGIN = 8.0
_BODY_FONT = "Helvetica"
_BODY_SIZE = 10.0
_HEADING_FONT = "Helvetica-Bold"
_HEADING_SIZE = 13.0
_LINE_HEIGHT = 10.5
_MAX_LINE_WIDTH = _PAGE_WIDTH - 2 * _MARGIN

# Line = (text, font, size)
_Line = tuple[str, str, float]


def _wrap(text: str, font: str, size: float, max_width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if stringWidth(candidate, font, size) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _section_lines(heading: str, paragraphs: list[str]) -> list[_Line]:
    lines: list[_Line] = [(heading, _HEADING_FONT, _HEADING_SIZE)]
    for paragraph in paragraphs:
        for wrapped in _wrap(paragraph, _BODY_FONT, _BODY_SIZE, _MAX_LINE_WIDTH):
            lines.append((wrapped, _BODY_FONT, _BODY_SIZE))
    return lines


def build_fixture_pdf(file_name: str, output_dir: Path) -> Path:
    """One PDF page per ``Item`` section.

    ``PDFParser._detect_sections`` assigns an *entire PyMuPDF text block* to
    whichever section heading it finds first -- and PyMuPDF tends to merge a
    tightly-packed page of drawString calls into a single block regardless of
    font-size changes between a heading and its body text. Putting each
    section on its own page (sized to just that section's line count, same
    density trick as before) sidesteps that entirely: a page can only ever
    contain one heading, so there's no ambiguity about which section its
    block(s) belong to.
    """
    spec = FIXTURE_DOCUMENTS[file_name]
    output_path = output_dir / file_name
    c: canvas.Canvas | None = None

    for heading, paragraphs in spec["sections"]:
        lines = _section_lines(heading, paragraphs)
        page_height = 2 * _MARGIN + len(lines) * _LINE_HEIGHT

        if c is None:
            c = canvas.Canvas(str(output_path), pagesize=(_PAGE_WIDTH, page_height))
        else:
            c.setPageSize((_PAGE_WIDTH, page_height))

        y = page_height - _MARGIN
        for text, font, size in lines:
            c.setFont(font, size)
            c.drawString(_MARGIN, y, text)
            y -= _LINE_HEIGHT
        c.showPage()

    assert c is not None, f"{file_name} has no sections to render"
    c.save()
    return output_path


def build_all_fixture_pdfs(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    return [build_fixture_pdf(name, output_dir) for name in FIXTURE_DOCUMENTS]


if __name__ == "__main__":
    default_dir = Path(__file__).parent / "documents"
    paths = build_all_fixture_pdfs(default_dir)
    print(f"Built {len(paths)} fixture PDFs in {default_dir}")
