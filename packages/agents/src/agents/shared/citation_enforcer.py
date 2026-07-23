"""Validation gate every agent output must pass before storage or display.

The Citation Enforcer is not a research agent — it never calls an LLM and
never produces content. It exists to defend the platform's core invariant:
every factual claim an agent makes must be traceable to an exact retrievable
quote. ``CitationEnforcer.validate`` runs six independent checks (coverage,
format, hallucination, unsourced numbers, unsourced speculation, unlabeled
inference) against an :class:`~agents.shared.message.AgentOutput` and
returns a :class:`ValidationResult` the LangGraph ``citation_validation``
node uses to either approve the output, ask the originating agent to retry
with a specific correction prompt, or mark it ``partial``/``failed``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from agents.shared.message import AgentOutput
from rag.retrieval.hybrid_retriever import HybridRetriever


@dataclass
class CheckResult:
    check_name: str
    passed: bool
    details: str
    failed_items: list[str] = field(default_factory=list)


@dataclass
class ValidationResult:
    approved: bool
    enforcer_status: str  # "approved", "partial", "failed"
    failed_checks: list[CheckResult]
    citation_coverage_pct: float
    retry_prompt: str | None
    hallucination_count: int


# ── Regex patterns ───────────────────────────────────────────────────────────

# Strict, well-formed citation: [Document Name, Section]: "exact quote (>=10 chars)"
CITATION_PATTERN = re.compile(
    r'\[([^\]]+),\s*([^\]]+)\]:\s*"([^"]{10,})"',
    re.MULTILINE,
)

# Anything that *looks like* an attempted citation (a label followed by a
# colon and a quoted string), whether or not it has brackets or a section —
# used only to find format violations, never to extract real citations.
_CITATION_ATTEMPT_PATTERN = re.compile(
    r'\[?[^\[\]\n]{1,80}\]?:\s*"[^"]{5,}"',
    re.MULTILINE,
)

NUMBER_PATTERN = re.compile(
    r'(?<!\[)\b\d[\d,]*\.?\d*\s*(?:billion|million|thousand|%|percent|B|M|K)\b',
    re.IGNORECASE,
)
SPECULATION_PATTERN = re.compile(
    r'\b(?:will\s+(?:grow|increase|decrease|improve|expand|reach)|'
    r'expects?\s+to|expected\s+to|is\s+expected\s+to|'
    r'analysts\s+predict|forecasts?|projects?)\b',
    re.IGNORECASE,
)
INFERENCE_PATTERN = re.compile(
    r'\b(?:appears?\s+to|seems?\s+to|likely|probably|presumably|'
    r'suggests?\s+that|implies?\s+that)\b',
    re.IGNORECASE,
)

_MIN_COVERAGE = 0.95
_PARTIAL_COVERAGE_FLOOR = 0.80


class CitationEnforcer:
    def __init__(self, retriever: HybridRetriever) -> None:
        self.retriever = retriever

    async def validate(
        self, output: AgentOutput, tenant_id: str, coverage_id: str
    ) -> ValidationResult:
        content = output.content
        checks = [
            self._check_citation_coverage(content),
            self._check_quote_format(content),
            await self._check_quotes_exist_in_rag(content, tenant_id, coverage_id),
            self._check_no_unsourced_numbers(content),
            self._check_no_future_speculation(content),
            self._check_inference_labeling(content),
        ]

        all_passed = all(c.passed for c in checks)
        citation_cov = self._compute_citation_coverage(content)
        hallucination_check = next(
            (c for c in checks if c.check_name == "quote_exists_in_rag"), None
        )
        hallucination_count = len(hallucination_check.failed_items) if hallucination_check else 0

        if all_passed:
            status = "approved"
        elif citation_cov >= _PARTIAL_COVERAGE_FLOOR:
            status = "partial"
        else:
            status = "failed"

        retry_prompt = None if all_passed else self._build_retry_prompt(checks, content)

        return ValidationResult(
            approved=all_passed,
            enforcer_status=status,
            failed_checks=[c for c in checks if not c.passed],
            citation_coverage_pct=citation_cov,
            retry_prompt=retry_prompt,
            hallucination_count=hallucination_count,
        )

    # ── Individual checks ────────────────────────────────────────────────────

    def _check_citation_coverage(self, content: str) -> CheckResult:
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        claim_paragraphs = [
            p
            for p in paragraphs
            if any(c.isdigit() for c in p) or re.search(r"\b(?:is|are|was|were|has|have|had)\b", p)
        ]
        cited_paragraphs = [p for p in claim_paragraphs if CITATION_PATTERN.search(p)]

        # A document with no factual claims at all has nothing to cite —
        # that's vacuously full coverage, not zero.
        coverage = 1.0 if not claim_paragraphs else len(cited_paragraphs) / len(claim_paragraphs)
        passed = coverage >= _MIN_COVERAGE

        return CheckResult(
            check_name="citation_coverage",
            passed=passed,
            details=f"Citation coverage: {coverage:.1%} (need >=95%)",
            failed_items=[
                f"Paragraph {i + 1} has no citation"
                for i, p in enumerate(claim_paragraphs)
                if p not in cited_paragraphs
            ],
        )

    def _check_quote_format(self, content: str) -> CheckResult:
        attempts = _CITATION_ATTEMPT_PATTERN.findall(content)
        malformed = [a for a in attempts if not CITATION_PATTERN.fullmatch(a)]

        passed = len(malformed) == 0
        return CheckResult(
            check_name="quote_format",
            passed=passed,
            details=f'Found {len(malformed)} malformed citations (need [Doc, Section]: "quote")',
            failed_items=malformed[:5],
        )

    async def _check_quotes_exist_in_rag(
        self, content: str, tenant_id: str, coverage_id: str
    ) -> CheckResult:
        citations = CITATION_PATTERN.findall(content)  # (doc, section, quote)
        not_found = []

        for _doc, _section, quote in citations:
            result = await self.retriever.retrieve_exact_quote(
                quote=quote.strip(), tenant_id=tenant_id, coverage_id=coverage_id
            )
            if result is None:
                not_found.append(f'"{quote[:60]}..."')

        passed = len(not_found) == 0
        return CheckResult(
            check_name="quote_exists_in_rag",
            passed=passed,
            details=f"{len(not_found)} quotes not found in document store (potential hallucinations)",
            failed_items=not_found[:5],
        )

    def _check_no_unsourced_numbers(self, content: str) -> CheckResult:
        sentences = re.split(r"(?<=[.!?])\s+", content)
        unsourced = []

        for i, sentence in enumerate(sentences):
            numbers = NUMBER_PATTERN.findall(sentence)
            if numbers:
                context = sentence + (" " + sentences[i + 1] if i + 1 < len(sentences) else "")
                if not CITATION_PATTERN.search(context):
                    unsourced.extend([f'"{n}" in: "{sentence[:80]}"' for n in numbers])

        passed = len(unsourced) == 0
        return CheckResult(
            check_name="no_unsourced_numbers",
            passed=passed,
            details=f"{len(unsourced)} numbers found without adjacent citations",
            failed_items=unsourced[:5],
        )

    def _check_no_future_speculation(self, content: str) -> CheckResult:
        sentences = re.split(r"(?<=[.!?])\s+", content)
        violations = []

        for sentence in sentences:
            if SPECULATION_PATTERN.search(sentence) and not CITATION_PATTERN.search(sentence):
                violations.append(sentence[:100])

        passed = len(violations) == 0
        return CheckResult(
            check_name="no_future_speculation",
            passed=passed,
            details=f"{len(violations)} speculative statements without source citation",
            failed_items=violations[:3],
        )

    def _check_inference_labeling(self, content: str) -> CheckResult:
        sentences = re.split(r"(?<=[.!?])\s+", content)
        unlabeled = []

        for sentence in sentences:
            if INFERENCE_PATTERN.search(sentence) and "(inferred from" not in sentence.lower():
                unlabeled.append(sentence[:100])

        passed = len(unlabeled) == 0
        return CheckResult(
            check_name="inference_labeling",
            passed=passed,
            details=f"{len(unlabeled)} inferred statements not labeled with (inferred from [source])",
            failed_items=unlabeled[:3],
        )

    def _compute_citation_coverage(self, content: str) -> float:
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
        claim_paragraphs = [p for p in paragraphs if any(c.isdigit() for c in p)]
        cited = [p for p in claim_paragraphs if CITATION_PATTERN.search(p)]
        return 1.0 if not claim_paragraphs else len(cited) / len(claim_paragraphs)

    def _build_retry_prompt(self, checks: list[CheckResult], _original_content: str) -> str:
        lines = [
            "Your previous output FAILED citation validation. Fix the following issues and rewrite:",
            "",
        ]
        for check in checks:
            if not check.passed:
                lines.append(f"FAILED: {check.check_name.upper().replace('_', ' ')}")
                lines.append(f"  Issue: {check.details}")
                if check.failed_items:
                    lines.append("  Specific failures:")
                    for item in check.failed_items[:3]:
                        lines.append(f"    - {item}")
                lines.append("")

        lines.extend(
            [
                "RULES TO FOLLOW:",
                '1. Every factual claim needs: [Document Name, Section]: "exact quote" -> interpretation',
                "2. Every number needs a citation in the same or next sentence",
                "3. Exact quotes must appear verbatim in the source documents — do not paraphrase",
                "4. Replace 'will grow/increase/expects to' with sourced management quotes or remove",
                "5. Mark inferences: '(inferred from [Document Name, Section])'",
                "",
                "Rewrite the full output following these rules exactly.",
            ]
        )
        return "\n".join(lines)
