"""Synthetic filing content for the eval fixture coverages.

Every fixture document is entirely invented (no real SEC filing text) but is
shaped like one -- ``Item 1``/``Item 1A``/``Item 7``/``Item 8`` headers so
``rag.ingestion.parsers.pdf_parser.PDFParser._detect_sections`` tags them the
same way it tags a real 10-K/10-Q/S-1, which is what lets the eval datasets'
``must_cite_sections`` checks and the agents' section-scoped RAG queries work
against them at all.

Each coverage is deliberately shaped to exercise one property the eval
datasets check for:
  - AAPL_EVAL_2023:   a normal, fully-disclosed multi-year filer.
  - NEWCO_EVAL_2023:  only one filing period exists, and it never discloses
                      debt/cash/FCF -- Q4 (Lynch) / Q6 (Munger) must come
                      back "Not found in uploaded documents."
  - STARTUP_EVAL_2023: pre-revenue -- there is no margin or historical
                      earnings data to cite at all.
  - SPARSE_EVAL_2023: revenue is disclosed but gross/operating margin is
                      deliberately never stated as a percentage anywhere --
                      an agent that reports one is fabricating it.
"""
from __future__ import annotations

from typing import Any

Section = tuple[str, list[str]]


def _doc(filing_type: str, period: str, sections: list[Section]) -> dict[str, Any]:
    return {"filing_type": filing_type, "period": period, "sections": sections}


FIXTURE_DOCUMENTS: dict[str, dict[str, Any]] = {
    # ── AAPL_EVAL_2023 ───────────────────────────────────────────────────────
    "aapl_10k_2021.pdf": _doc(
        "10-K",
        "FY2021",
        [
            (
                "Item 1. Business",
                [
                    "Aptus Consumer Devices Inc. (the Company) designs, manufactures, and markets "
                    "smartphones, personal computers, tablets, wearables, and related accessories, "
                    "and sells a variety of related services including cloud storage, digital "
                    "content subscriptions, and payment services.",
                    "The Company sells its products and services to consumers, small and mid-sized "
                    "businesses, and government and education customers worldwide through its retail "
                    "stores, online stores, and third-party resellers, generating revenue from both "
                    "hardware sales and recurring service subscriptions.",
                ],
            ),
            (
                "Item 1A. Risk Factors",
                [
                    "The Company's business is highly competitive and subject to rapid technological "
                    "change; competitors may introduce products that make the Company's products less "
                    "desirable or obsolete.",
                    "Global economic conditions could materially adversely affect the Company's "
                    "revenue, particularly through currency fluctuations, component shortages, and "
                    "disruption to the Company's global supply chain.",
                ],
            ),
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Total net sales for fiscal 2021 were $365.8 billion, an increase from the prior "
                    "fiscal year, driven primarily by strength in hardware and services revenue.",
                    "Gross margin for fiscal 2021 was 41.8 percent of net sales, and operating margin "
                    "was 29.8 percent of net sales.",
                    "The Company believes its ecosystem of integrated hardware, software, and "
                    "services creates high switching costs for customers, which management views as "
                    "the primary source of the Company's durable competitive advantage.",
                ],
            ),
            (
                "Item 8. Financial Statements",
                [
                    "As of the end of fiscal 2021, the Company had total debt of $124.7 billion and "
                    "cash and cash equivalents of $34.9 billion.",
                    "Free cash flow for fiscal 2021 was $92.9 billion.",
                ],
            ),
        ],
    ),
    "aapl_10k_2022.pdf": _doc(
        "10-K",
        "FY2022",
        [
            (
                "Item 1. Business",
                [
                    "Aptus Consumer Devices Inc. designs, manufactures, and markets smartphones, "
                    "personal computers, tablets, wearables, and related accessories, and sells a "
                    "variety of related services including cloud storage, digital content "
                    "subscriptions, and payment services.",
                ],
            ),
            (
                "Item 1A. Risk Factors",
                [
                    "The Company depends on component suppliers concentrated in a small number of "
                    "countries, and any disruption to those suppliers could materially harm the "
                    "Company's ability to meet customer demand.",
                    "Regulatory scrutiny of the Company's App Store business practices has increased "
                    "in several jurisdictions and could result in fines or forced changes to the "
                    "Company's services revenue model.",
                ],
            ),
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Total net sales for fiscal 2022 were $394.3 billion, an increase of 8 percent "
                    "compared to fiscal 2021, driven by growth in Services and Mac revenue.",
                    "Gross margin for fiscal 2022 was 43.3 percent of net sales, and operating margin "
                    "was 30.3 percent of net sales.",
                ],
            ),
            (
                "Item 8. Financial Statements",
                [
                    "As of the end of fiscal 2022, the Company had total debt of $120.1 billion and "
                    "cash and cash equivalents of $23.6 billion.",
                    "Free cash flow for fiscal 2022 was $111.4 billion.",
                ],
            ),
        ],
    ),
    "aapl_10k_2023.pdf": _doc(
        "10-K",
        "FY2023",
        [
            (
                "Item 1. Business",
                [
                    "Aptus Consumer Devices Inc. designs, manufactures, and markets smartphones, "
                    "personal computers, tablets, wearables, and related accessories, and sells a "
                    "variety of related services including cloud storage, digital content "
                    "subscriptions, and payment services, to consumers and businesses worldwide.",
                ],
            ),
            (
                "Item 1A. Risk Factors",
                [
                    "The Company's future performance depends significantly on its ability to "
                    "introduce new products and services that customers want, and any failure to do "
                    "so could adversely affect the Company's net sales.",
                    "Weakness in foreign currencies relative to the U.S. dollar has adversely affected "
                    "and could continue to adversely affect the U.S. dollar value of the Company's "
                    "foreign currency-denominated sales and earnings.",
                ],
            ),
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Total net sales for fiscal 2023 were $383.3 billion, a decrease of 3 percent "
                    "compared to fiscal 2022, primarily due to weakness in Mac and iPhone sales.",
                    "Gross margin for fiscal 2023 was 44.1 percent of net sales, and operating margin "
                    "was 29.8 percent of net sales.",
                    "Management believes the Company's installed base of active devices and the "
                    "resulting recurring Services revenue represent the Company's single strongest "
                    "long-term competitive advantage.",
                ],
            ),
            (
                "Item 8. Financial Statements",
                [
                    "As of the end of fiscal 2023, the Company had total debt of $111.1 billion and "
                    "cash and cash equivalents of $29.9 billion.",
                    "Free cash flow for fiscal 2023 was $99.6 billion.",
                ],
            ),
        ],
    ),
    "aapl_10q_2023_q3.pdf": _doc(
        "10-Q",
        "Q3 FY2023",
        [
            (
                "Item 1. Business",
                [
                    "Aptus Consumer Devices Inc. designs, manufactures, and markets smartphones, "
                    "personal computers, tablets, wearables, and related accessories and services.",
                ],
            ),
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Net sales for the third quarter of fiscal 2023 were $81.8 billion, roughly flat "
                    "compared to the third quarter of fiscal 2022.",
                    "Foreign exchange continued to be a headwind, reducing revenue growth by nearly "
                    "two percentage points during the quarter.",
                    "Management expects fiscal fourth quarter revenue to grow year over year, similar "
                    "to the growth rate achieved in the June quarter, driven by Services momentum.",
                ],
            ),
        ],
    ),
    "aapl_10q_2023_q4.pdf": _doc(
        "10-Q",
        "Q4 FY2023",
        [
            (
                "Item 1. Business",
                [
                    "Aptus Consumer Devices Inc. designs, manufactures, and markets smartphones, "
                    "personal computers, tablets, wearables, and related accessories and services.",
                ],
            ),
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Net sales for the fourth quarter of fiscal 2023 were $89.5 billion, up 1 percent "
                    "year over year, consistent with the growth the Company guided to last quarter.",
                    "Foreign exchange continued to be a headwind, reducing revenue growth by nearly "
                    "two percentage points during the quarter.",
                    "Services revenue reached a new all-time high, growing 16 percent year over year "
                    "and reaching an installed base of over 1 billion paid subscriptions.",
                    "Gross margin for the fourth quarter of fiscal 2023 was 45.2 percent of net sales, "
                    "up from 42.9 percent in the fourth quarter of fiscal 2022.",
                ],
            ),
        ],
    ),
    # ── NEWCO_EVAL_2023 (single filing period; no debt/cash/FCF disclosed) ──
    "newco_10k_2023.pdf": _doc(
        "10-K",
        "FY2023",
        [
            (
                "Item 1. Business",
                [
                    "Newco Workflow Systems Inc. sells subscription workflow-automation software to "
                    "mid-market manufacturing companies, charging customers an annual per-seat "
                    "license fee for access to its cloud-hosted platform.",
                    "The Company was founded in 2019 and completed its initial public offering in "
                    "2023; fiscal 2023 is the Company's first full year of financial reporting as a "
                    "public company.",
                ],
            ),
            (
                "Item 1A. Risk Factors",
                [
                    "The Company has a limited operating history as a public company, which makes it "
                    "difficult to evaluate the Company's future prospects based on historical "
                    "results.",
                    "The Company depends on a small number of large customers for a significant "
                    "portion of its revenue, and the loss of any of these customers could materially "
                    "harm the Company's results of operations.",
                ],
            ),
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Total revenue for fiscal 2023 was $42.1 million, an increase of 38 percent "
                    "compared to the prior fiscal year, driven primarily by new customer additions.",
                    "Gross margin for fiscal 2023 was 71 percent of revenue, reflecting the Company's "
                    "cloud-hosted delivery model.",
                ],
            ),
        ],
    ),
    "newco_10q_2023_q1.pdf": _doc(
        "10-Q",
        "Q1 FY2023",
        [
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Total revenue for the first quarter of fiscal 2023 was $9.8 million, an increase "
                    "of 34 percent compared to the first quarter of the prior fiscal year.",
                ],
            ),
        ],
    ),
    # ── STARTUP_EVAL_2023 (pre-revenue S-1) ─────────────────────────────────
    "startup_s1.pdf": _doc(
        "S-1",
        "FY2023",
        [
            (
                "Item 1. Business",
                [
                    "Helix Biologics Inc. is a clinical-stage biotechnology company developing a "
                    "gene-editing therapy for a rare inherited metabolic disorder. The Company has "
                    "not generated any revenue from product sales since inception and does not "
                    "expect to generate product revenue unless and until it receives regulatory "
                    "approval for its lead product candidate.",
                ],
            ),
            (
                "Item 1A. Risk Factors",
                [
                    "The Company has incurred significant losses since inception and expects to "
                    "continue to incur losses for the foreseeable future; the Company's ability to "
                    "continue as a going concern depends on its ability to raise additional capital.",
                    "The Company's lead product candidate is still in clinical trials, and there is "
                    "no guarantee that it will ever receive regulatory approval.",
                ],
            ),
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "The Company has not generated any revenue since inception and does not expect "
                    "to generate revenue until it obtains regulatory approval for a product "
                    "candidate, if ever.",
                    "As of the most recent balance sheet date, the Company had cash and cash "
                    "equivalents of $18.2 million, which management believes is sufficient to fund "
                    "operations for approximately five quarters at the Company's current burn rate.",
                ],
            ),
        ],
    ),
    # ── SPARSE_EVAL_2023 (revenue disclosed; margin percentage never is) ────
    "sparse_10k_no_margins.pdf": _doc(
        "10-K",
        "FY2023",
        [
            (
                "Item 1. Business",
                [
                    "Meridian Industrial Supply Corp. distributes replacement parts for industrial "
                    "machinery to regional equipment dealers across North America.",
                ],
            ),
            (
                "Item 1A. Risk Factors",
                [
                    "The Company's business is sensitive to fluctuations in industrial production "
                    "activity and capital spending by its equipment-dealer customers.",
                ],
            ),
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Total revenue for fiscal 2023 was $214.6 million, compared to $198.2 million in "
                    "the prior fiscal year.",
                    "The Company does not separately disclose cost of revenue by product line and "
                    "therefore does not present a gross margin or operating margin percentage in this "
                    "filing.",
                    "Net income for fiscal 2023 was $11.4 million.",
                ],
            ),
            (
                "Item 8. Financial Statements",
                [
                    "Total revenue was $214.6 million and net income was $11.4 million for fiscal "
                    "2023, as reported in the Company's consolidated statements of operations.",
                ],
            ),
        ],
    ),
    "sparse_10q_no_margins_q2.pdf": _doc(
        "10-Q",
        "Q2 FY2024",
        [
            (
                "Item 7. Management's Discussion and Analysis",
                [
                    "Total revenue for the second quarter of fiscal 2024 was $56.3 million, compared "
                    "to $52.9 million in the second quarter of fiscal 2023.",
                    "The Company does not separately disclose cost of revenue by product line and "
                    "therefore does not present a gross margin or operating margin percentage in this "
                    "filing.",
                ],
            ),
        ],
    ),
}


# label -> {ticker, company_name, exchange, industry_name, documents}
FIXTURE_COVERAGES: dict[str, dict[str, Any]] = {
    "AAPL_EVAL_2023": {
        "ticker": "AAPL",
        "company_name": "Aptus Consumer Devices Inc.",
        "exchange": "NASDAQ",
        "industry_name": "Enterprise Software",
        "documents": [
            "aapl_10k_2021.pdf",
            "aapl_10k_2022.pdf",
            "aapl_10k_2023.pdf",
            "aapl_10q_2023_q3.pdf",
            "aapl_10q_2023_q4.pdf",
        ],
    },
    "NEWCO_EVAL_2023": {
        "ticker": "NEWCO",
        "company_name": "Newco Workflow Systems Inc.",
        "exchange": "NASDAQ",
        "industry_name": "Regional Banking",
        "documents": ["newco_10k_2023.pdf", "newco_10q_2023_q1.pdf"],
    },
    "STARTUP_EVAL_2023": {
        "ticker": "HLXB",
        "company_name": "Helix Biologics Inc.",
        "exchange": "NASDAQ",
        "industry_name": None,
        "documents": ["startup_s1.pdf"],
    },
    "SPARSE_EVAL_2023": {
        "ticker": "MISC",
        "company_name": "Meridian Industrial Supply Corp.",
        "exchange": "NYSE",
        "industry_name": "Semiconductor Capital Equipment",
        "documents": ["sparse_10k_no_margins.pdf", "sparse_10q_no_margins_q2.pdf"],
    },
}
