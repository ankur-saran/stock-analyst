"""Command-line quality-eval runner — the Phase 3 CI gate for all 7 agents.

Runs one agent's golden dataset (``eval/datasets/{agent}_eval.json``) against
a live API + Celery worker stack, using the eval fixture coverages built by
``eval.fixtures.setup_fixtures`` (see ``eval/fixtures/manifest.json`` for the
label -> real-UUID mapping this runner resolves each case's ``coverage_id``
against).

For every case, `EvalRunner`:
  1. Dispatches the agent as a real task through the FastAPI + Celery path
     (``POST /coverages/{coverage_id}/tasks/{agent_task}``) -- never calls
     the agent class directly, so this exercises exactly what a real
     analyst's click in the UI exercises.
  2. Polls ``GET /tasks/{task_id}`` until the task leaves the queue.
  3. Reads the agent's raw output straight off ``task.result`` (the
     orchestrator always populates this, even for a rejected/prerequisite-
     missing output that never became a ``research_outputs`` row).
  4. Evaluates that content against every check the case declares, plus a
     citation-coverage check that always runs, plus a real
     ``CitationEnforcer`` pass (against the same eval coverage's real index)
     to get an honest hallucination/paraphrase count for the report.

Cases run strictly sequentially (never ``asyncio.gather``) -- the constraint
is deliberate: everything here dispatches through the same handful of Celery
workers the interactive product uses, and an eval run is not the place to
introduce queue contention that could distort the very latency numbers it is
measuring.

Usage:
    python -m eval.runners.run_eval --agent lynch_pitch --env dev
    python -m eval.runners.run_eval --agent lynch_pitch --env dev --output-html eval/reports/
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from jinja2 import Environment, FileSystemLoader, select_autoescape
from qdrant_client import QdrantClient

from agents.shared.citation_enforcer import (
    CITATION_PATTERN,
    _CITATION_ATTEMPT_PATTERN,  # reused deliberately -- see module docstring
    CitationEnforcer,
)
from agents.shared.message import AgentOutput, AgentType
from rag.connectors.qdrant_client import QdrantConnector
from rag.ingestion.pipeline import EmbeddingPipeline
from rag.retrieval.hybrid_retriever import HybridRetriever
from shared.config import Settings

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DATASETS_DIR = _REPO_ROOT / "eval" / "datasets"
_MANIFEST_PATH = _REPO_ROOT / "eval" / "fixtures" / "manifest.json"
_DEFAULT_REPORTS_DIR = _REPO_ROOT / "eval" / "reports"
_TEMPLATE_DIR = Path(__file__).parent

_ALL_AGENTS = {
    "lynch_pitch",
    "munger_invert",
    "earnings_monitor",
    "industry_analyst",
    "kpi_tracker",
}

_ENVIRONMENTS: dict[str, str] = {
    "dev": "http://localhost:8000",
    "staging": "http://staging.stockanalyst.internal",
}

_POLL_INTERVAL_SECONDS = 2.0
_POLL_TIMEOUT_SECONDS = 300.0
_NOT_FOUND_TEXT = "not found in uploaded documents"
_PERCENT_RE = re.compile(r"\d+(?:\.\d+)?\s*%")
_KPI_UPSERTED_RE = re.compile(r"(\d+)\s+KPI value\(s\) upserted")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slug(text: str) -> str:
    return _SLUG_RE.sub("_", text.lower()).strip("_")


# ── Result types ─────────────────────────────────────────────────────────────


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


@dataclass
class CaseResult:
    test_id: str
    name: str
    passed: bool
    checks: list[CheckResult]
    citation_coverage_pct: float
    hallucination_count: int
    paraphrase_count: int
    citations_found: int
    latency_ms: int
    llm_used: str | None
    tokens_used: int
    error: str | None = None


@dataclass
class EvalReport:
    agent: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return sum(1 for r in self.results if r.passed) / len(self.results) if self.results else 0.0

    @property
    def avg_citation_coverage(self) -> float:
        return statistics.fmean(r.citation_coverage_pct for r in self.results) if self.results else 0.0

    @property
    def avg_latency_ms(self) -> float:
        return statistics.fmean(r.latency_ms for r in self.results) if self.results else 0.0

    @property
    def hallucination_rate(self) -> float:
        total_citations = sum(r.citations_found for r in self.results)
        total_hallucinations = sum(r.hallucination_count for r in self.results)
        return total_hallucinations / total_citations if total_citations else 0.0

    @property
    def total_paraphrase_warnings(self) -> int:
        return sum(r.paraphrase_count for r in self.results)


# ── Runner ───────────────────────────────────────────────────────────────────


class EvalRunner:
    def __init__(
        self,
        agent_name: str,
        env: str,
        base_url: str,
        token: str,
        retriever: HybridRetriever | None = None,
    ) -> None:
        if agent_name not in _ALL_AGENTS:
            raise ValueError(f"Unknown agent '{agent_name}'. Known: {sorted(_ALL_AGENTS)}")
        self.agent_name = agent_name
        self.env = env
        self.dataset = self._load_dataset(_DATASETS_DIR / f"{agent_name}_eval.json")
        self.manifest = self._load_manifest()
        self.client = httpx.AsyncClient(
            base_url=base_url, headers={"Authorization": f"Bearer {token}"}, timeout=30.0
        )
        self.retriever = retriever or _build_retriever(Settings())
        self.enforcer = CitationEnforcer(retriever=self.retriever)

    @staticmethod
    def _load_dataset(path: Path) -> dict[str, Any]:
        with path.open(encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def _load_manifest() -> dict[str, Any]:
        if not _MANIFEST_PATH.exists():
            raise FileNotFoundError(
                f"{_MANIFEST_PATH} not found -- run "
                "`python -m eval.fixtures.setup_fixtures` first to build the eval coverages."
            )
        with _MANIFEST_PATH.open(encoding="utf-8") as fh:
            return json.load(fh)

    async def aclose(self) -> None:
        await self.client.aclose()

    # ── Top-level entry point ────────────────────────────────────────────────

    async def run_all(self) -> EvalReport:
        results: list[CaseResult] = []
        # Sequential by design -- see module docstring.
        for case in self.dataset["test_cases"]:
            result = await self.run_case(case)
            results.append(result)
        return EvalReport(agent=self.agent_name, results=results)

    async def run_case(self, case: dict[str, Any]) -> CaseResult:
        start = time.monotonic()
        try:
            content, llm_used, tokens_used = await self._execute_case(case)
        except Exception as exc:  # noqa: BLE001 - surfaced as a failed case, not a crashed run
            latency_ms = int((time.monotonic() - start) * 1000)
            return CaseResult(
                test_id=case["test_id"],
                name=case["name"],
                passed=False,
                checks=[CheckResult(name="execution", passed=False, detail=str(exc))],
                citation_coverage_pct=0.0,
                hallucination_count=0,
                paraphrase_count=0,
                citations_found=0,
                latency_ms=latency_ms,
                llm_used=None,
                tokens_used=0,
                error=str(exc),
            )

        checks = self._run_checks(case, content)
        hallucination_count, paraphrase_count, citations_found = await self._score_hallucinations(
            case, content
        )
        max_hallucinations = case.get("max_hallucinations", 0)
        checks.append(
            CheckResult(
                name="no_hallucinations",
                passed=hallucination_count <= max_hallucinations,
                detail=(
                    f"{hallucination_count} confirmed hallucination(s) (max {max_hallucinations}); "
                    f"{paraphrase_count} paraphrase warning(s) (informational only)"
                ),
            )
        )

        latency_ms = int((time.monotonic() - start) * 1000)
        return CaseResult(
            test_id=case["test_id"],
            name=case["name"],
            passed=all(c.passed for c in checks),
            checks=checks,
            citation_coverage_pct=_citation_coverage(content),
            hallucination_count=hallucination_count,
            paraphrase_count=paraphrase_count,
            citations_found=citations_found,
            latency_ms=latency_ms,
            llm_used=llm_used,
            tokens_used=tokens_used,
        )

    # ── Task dispatch / polling ──────────────────────────────────────────────

    async def _execute_case(self, case: dict[str, Any]) -> tuple[str, str | None, int]:
        coverage_id = self._resolve_coverage_id(case["coverage_id"])

        if self.agent_name == "industry_analyst":
            resp = await self.client.post(
                f"/coverages/{coverage_id}/tasks/industry-analysis",
                json={"industry_name": case["industry_name"]},
            )
        elif self.agent_name == "earnings_monitor":
            new_doc_id = self._resolve_document_id(case["coverage_id"], case["new_document"])
            resp = await self.client.post(
                f"/coverages/{coverage_id}/tasks/earnings_monitor",
                json={"skill": "quarterly_update", "payload": {"new_document_id": new_doc_id}},
            )
        else:
            resp = await self.client.post(
                f"/coverages/{coverage_id}/tasks/{self.agent_name}",
                json={"skill": "default", "payload": {}},
            )
        resp.raise_for_status()
        task_id = resp.json()["task_id"]

        task = await self._poll_task(task_id)
        if task["status"] == "failed":
            raise RuntimeError(f"task {task_id} failed: {task.get('error')}")

        result = task.get("result") or {}
        return result.get("content", ""), result.get("llm_used"), int(result.get("tokens_used", 0))

    async def _poll_task(self, task_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + _POLL_TIMEOUT_SECONDS
        while True:
            resp = await self.client.get(f"/tasks/{task_id}")
            resp.raise_for_status()
            task: dict[str, Any] = resp.json()
            if task["status"] in ("completed", "failed", "cancelled"):
                return task
            if time.monotonic() > deadline:
                raise TimeoutError(f"task {task_id} did not complete within {_POLL_TIMEOUT_SECONDS}s")
            await asyncio.sleep(_POLL_INTERVAL_SECONDS)

    def _resolve_coverage_id(self, label: str) -> str:
        try:
            return str(self.manifest["coverages"][label]["coverage_id"])
        except KeyError:
            raise KeyError(
                f"coverage label '{label}' not found in {_MANIFEST_PATH} -- "
                "did eval.fixtures.setup_fixtures run for this environment?"
            ) from None

    def _resolve_document_id(self, coverage_label: str, file_name: str) -> str:
        try:
            return str(self.manifest["coverages"][coverage_label]["documents"][file_name])
        except KeyError:
            raise KeyError(
                f"document '{file_name}' not found under coverage '{coverage_label}' in {_MANIFEST_PATH}"
            ) from None

    # ── Hallucination scoring (real CitationEnforcer, real retriever) ───────

    async def _score_hallucinations(
        self, case: dict[str, Any], content: str
    ) -> tuple[int, int, int]:
        citations_found = len(CITATION_PATTERN.findall(content))
        if citations_found == 0:
            return 0, 0, 0

        coverage_id = self._resolve_coverage_id(case["coverage_id"])
        tenant_id = str(self.manifest["tenant_id"])
        output = AgentOutput(
            message_id="eval",
            agent=AgentType(self.agent_name),
            task_id="eval",
            coverage_id=coverage_id,
            tenant_id=tenant_id,
            content=content,
            citations=[],
            citation_coverage_pct=0.0,
            llm_used="",
            tokens_used=0,
            latency_ms=0,
        )
        result = await self.enforcer.validate(output, tenant_id, coverage_id)
        return result.hallucination_count, len(result.paraphrase_warnings), citations_found

    # ── Checks ────────────────────────────────────────────────────────────────

    def _run_checks(self, case: dict[str, Any], content: str) -> list[CheckResult]:
        checks: list[CheckResult] = []

        if "must_start_with" in case:
            prefix = case["must_start_with"]
            passed = content.strip().startswith(prefix)
            checks.append(
                CheckResult("must_start_with", passed, f"content should start with '{prefix}'")
            )

        if case.get("skip_citation_checks"):
            # e.g. earnings_monitor's PREREQUISITE_MISSING short-circuit --
            # there is no cited prose to evaluate at all.
            return checks

        question_blocks = _question_blocks(content)
        lower_content = content.lower()

        for q_num in case.get("must_answer_questions", []):
            found = q_num in question_blocks
            checks.append(
                CheckResult(f"Q{q_num}_answered", found, f"Question {q_num} header {'found' if found else 'MISSING'}")
            )

        for token in case.get("must_contain_not_found", []):
            match = re.match(r"^Q(\d+)$", token)
            if not match:
                continue
            q_num = int(match.group(1))
            body = question_blocks.get(q_num, "")
            passed = _NOT_FOUND_TEXT in body.lower()
            checks.append(
                CheckResult(
                    f"{token}_states_not_found",
                    passed,
                    f"{token} {'correctly' if passed else 'incorrectly'} states 'Not found in uploaded documents'",
                )
            )

        for key, value in case.items():
            per_question = re.match(r"^q(\d+)_must_contain_not_found$", key)
            if per_question and value:
                q_num = int(per_question.group(1))
                body = question_blocks.get(q_num, "")
                passed = _NOT_FOUND_TEXT in body.lower()
                checks.append(
                    CheckResult(
                        key,
                        passed,
                        f"Q{q_num} {'correctly' if passed else 'incorrectly'} states 'Not found in uploaded documents'",
                    )
                )
                continue

            not_fabricated = re.match(r"^must_not_state_(.+)$", key)
            if not_fabricated and value:
                metric_phrase = not_fabricated.group(1).replace("_", " ")
                fabricated = _metric_stated_as_number(content, metric_phrase)
                checks.append(
                    CheckResult(
                        key,
                        not fabricated,
                        f"'{metric_phrase}' {'was NOT fabricated as a percentage (good)' if not fabricated else 'was stated as a percentage the source never discloses (BAD)'}",
                    )
                )

        for phrase in case.get("must_not_contain", []):
            found = phrase.lower() in lower_content
            checks.append(
                CheckResult(f"no_{_slug(phrase)}", not found, f"Forbidden phrase '{phrase}' {'FOUND (bad)' if found else 'absent (good)'}")
            )

        for phrase in case.get("must_contain_all", []):
            found = phrase.lower() in lower_content
            checks.append(
                CheckResult(f"has_{_slug(phrase)}", found, f"Required phrase '{phrase}' {'found' if found else 'MISSING'}")
            )

        for phrase in case.get("must_contain_sections", []):
            found = phrase.lower() in lower_content
            checks.append(
                CheckResult(f"section_{_slug(phrase)}", found, f"Section '{phrase}' {'found' if found else 'MISSING'}")
            )

        any_list = case.get("must_contain_any", [])
        if any_list:
            found = any(p.lower() in lower_content for p in any_list)
            checks.append(
                CheckResult("must_contain_any", found, f"At least one of {any_list} {'found' if found else 'MISSING'}")
            )

        if "must_contain_regex" in case:
            pattern = re.compile(case["must_contain_regex"])
            found = bool(pattern.search(content))
            checks.append(
                CheckResult("must_contain_regex", found, f"Pattern {case['must_contain_regex']!r} {'matched' if found else 'did NOT match'}")
            )

        if "must_cite_sections" in case:
            cited_sections = [section.strip().lower() for _doc, section, _quote in CITATION_PATTERN.findall(content)]
            for required in case["must_cite_sections"]:
                found = any(required.lower() in s for s in cited_sections)
                checks.append(
                    CheckResult(f"cites_{_slug(required)}", found, f"A citation referencing '{required}' {'found' if found else 'MISSING'}")
                )

        min_cov = case.get("min_citation_coverage", 0.95)
        actual_cov = _citation_coverage(content)
        checks.append(
            CheckResult("citation_coverage", actual_cov >= min_cov, f"Citation coverage: {actual_cov:.1%} (need >= {min_cov:.0%})")
        )

        word_count = len(content.split())
        if "max_word_count" in case:
            checks.append(
                CheckResult("max_word_count", word_count <= case["max_word_count"], f"Word count: {word_count} (max {case['max_word_count']})")
            )
        if "min_word_count" in case:
            checks.append(
                CheckResult("min_word_count", word_count >= case["min_word_count"], f"Word count: {word_count} (min {case['min_word_count']})")
            )

        if "all_citations_must_match_regex" in case:
            strict = re.compile(case["all_citations_must_match_regex"])
            attempts = _CITATION_ATTEMPT_PATTERN.findall(content)
            malformed = [a for a in attempts if not strict.fullmatch(a)]
            checks.append(
                CheckResult("citation_format", len(malformed) == 0, f"{len(malformed)} citation(s) don't match the required format")
            )

        if "min_kpis_upserted" in case:
            match = _KPI_UPSERTED_RE.search(content)
            count = int(match.group(1)) if match else 0
            checks.append(
                CheckResult("min_kpis_upserted", count >= case["min_kpis_upserted"], f"{count} KPI value(s) upserted (need >= {case['min_kpis_upserted']})")
            )

        return checks


def _question_blocks(content: str) -> dict[int, str]:
    header_re = re.compile(r"^###\s*Q(\d+):\s*(.+)$", re.MULTILINE)
    headers = list(header_re.finditer(content))
    blocks: dict[int, str] = {}
    for i, header in enumerate(headers):
        start = header.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(content)
        blocks[int(header.group(1))] = content[start:end]
    return blocks


def _citation_coverage(content: str) -> float:
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]
    claim_paragraphs = [p for p in paragraphs if any(c.isdigit() for c in p)]
    cited = [p for p in claim_paragraphs if CITATION_PATTERN.search(p)]
    return 1.0 if not claim_paragraphs else len(cited) / len(claim_paragraphs)


def _metric_stated_as_number(content: str, metric_phrase: str) -> bool:
    sentences = re.split(r"(?<=[.!?])\s+", content)
    metric_re = re.compile(re.escape(metric_phrase), re.IGNORECASE)
    return any(metric_re.search(s) and _PERCENT_RE.search(s) for s in sentences)


def _build_retriever(settings: Settings) -> HybridRetriever:
    raw_client = QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)
    qdrant = QdrantConnector(host=settings.qdrant_host, port=settings.qdrant_port, client=raw_client)
    embedder = EmbeddingPipeline(ollama_url=settings.ollama_base_url, qdrant_client=raw_client)
    return HybridRetriever(qdrant=qdrant, embedding_pipeline=embedder)


# ── Environment / auth resolution ───────────────────────────────────────────


def _resolve_base_url(env: str) -> str:
    override = os.environ.get("EVAL_API_BASE_URL")
    if override:
        return override
    try:
        return _ENVIRONMENTS[env]
    except KeyError:
        raise ValueError(f"Unknown --env '{env}'. Known environments: {sorted(_ENVIRONMENTS)}") from None


async def _resolve_token(explicit: str | None) -> str:
    if explicit:
        return explicit
    env_token = os.environ.get("EVAL_BEARER_TOKEN")
    if env_token:
        return env_token

    settings = Settings()
    secret = settings.keycloak_client_secret.get_secret_value()
    if secret in ("", "changeme"):
        raise RuntimeError(
            "No bearer token available. Pass --token, set EVAL_BEARER_TOKEN, or configure "
            "a real KEYCLOAK_CLIENT_SECRET so this runner can fetch one via a "
            "client-credentials grant for the eval service account."
        )

    token_url = f"{settings.keycloak_url}/realms/{settings.keycloak_realm}/protocol/openid-connect/token"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": settings.keycloak_client_id,
                "client_secret": secret,
            },
        )
        resp.raise_for_status()
        token: str = resp.json()["access_token"]
        return token


# ── Reporting ────────────────────────────────────────────────────────────────


def _print_report(report: EvalReport) -> None:
    print(f"\n=== {report.agent} eval — {len(report.results)} case(s) ===")
    for r in report.results:
        status = "PASS" if r.passed else "FAIL"
        print(f"  [{status}] {r.test_id}: {r.name} ({r.latency_ms}ms, coverage={r.citation_coverage_pct:.0%})")
        for check in r.checks:
            if not check.passed:
                print(f"          FAILED check '{check.name}': {check.detail}")
        if r.error:
            print(f"          ERROR: {r.error}")

    print(
        f"\nPass rate: {report.pass_rate:.0%}  |  "
        f"Avg citation coverage: {report.avg_citation_coverage:.1%}  |  "
        f"Avg latency: {report.avg_latency_ms:.0f}ms  |  "
        f"Hallucination rate: {report.hallucination_rate:.2%}  |  "
        f"Paraphrase warnings: {report.total_paraphrase_warnings}"
    )


def generate_html_report(report: EvalReport, output_path: Path) -> None:
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("report_template.html.j2")
    rendered = template.render(
        report=report,
        generated_at=datetime.now(timezone.utc).isoformat(),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


# ── CLI ──────────────────────────────────────────────────────────────────────


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the golden eval dataset for one agent.")
    parser.add_argument("--agent", required=True, choices=sorted(_ALL_AGENTS))
    parser.add_argument("--env", default="dev", help="Environment name (dev/staging) or set EVAL_API_BASE_URL")
    parser.add_argument("--output-html", default=None, help="Directory to write the HTML report into")
    parser.add_argument("--token", default=None, help="Bearer token (else EVAL_BEARER_TOKEN or Keycloak client-credentials)")
    parser.add_argument("--base-url", default=None, help="Override the resolved API base URL")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> EvalReport:
    token = await _resolve_token(args.token)
    base_url = args.base_url or _resolve_base_url(args.env)

    runner = EvalRunner(args.agent, args.env, base_url=base_url, token=token)
    try:
        report = await runner.run_all()
    finally:
        await runner.aclose()

    _print_report(report)

    if args.output_html:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output_path = Path(args.output_html) / f"{args.agent}_{timestamp}.html"
        generate_html_report(report, output_path)
        print(f"\nHTML report: {output_path}")

        # Sibling machine-readable summary -- what the CI eval-gate job
        # (.gitea/workflows/ci.yml) actually parses to enforce the
        # avg_citation_coverage / hallucination_rate thresholds, since those
        # aren't reflected in this process's exit code (see `main()` below).
        summary_path = output_path.with_suffix(".json")
        summary_path.write_text(json.dumps(_summary_dict(report), indent=2), encoding="utf-8")
        print(f"Summary JSON: {summary_path}")

    return report


def _summary_dict(report: EvalReport) -> dict[str, Any]:
    return {
        "agent": report.agent,
        "pass_rate": report.pass_rate,
        "avg_citation_coverage": report.avg_citation_coverage,
        "avg_latency_ms": report.avg_latency_ms,
        "hallucination_rate": report.hallucination_rate,
        "total_paraphrase_warnings": report.total_paraphrase_warnings,
        "case_count": len(report.results),
        "failed_case_ids": [r.test_id for r in report.results if not r.passed],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    report = asyncio.run(_main_async(args))
    return 0 if report.pass_rate == 1.0 else 1


if __name__ == "__main__":
    sys.exit(main())
