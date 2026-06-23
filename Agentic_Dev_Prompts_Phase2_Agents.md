# Stock Analyst AI — Agentic Development Prompts
## Phase 2: Core Agents (Weeks 8–13)

Each prompt is self-contained and ready to paste directly into Claude Code or any agentic coding tool.
Run these in numbered order — each agent builds on the shared infrastructure established earlier.

---

## PROMPT 2.1 — Shared Agent Infrastructure: BaseAgent, AgentMessage & LangGraph Graph

```
You are implementing the shared agent infrastructure for the Stock Analyst AI platform.
Phase 1 is complete: documents can be ingested, chunked, embedded, and retrieved.
The HybridRetriever is working. The Citation Enforcer will be built in the next step.
Working directory: packages/agents/

CONTEXT:
The system uses LangGraph for stateful, persistent agent orchestration. All 7 agents share:
- A common message envelope (AgentMessage) for inter-agent communication
- A BaseAgent class that handles LLM routing, audit logging, and error wrapping
- A LangGraph state graph representing the full coverage research workflow
All agents must log every call to agent_audit_log in PostgreSQL.

TASK 1 — Create packages/agents/shared/message.py:
Implement the AgentMessage protocol from the architecture spec exactly:

from enum import Enum
from pydantic import BaseModel, Field
import uuid
from datetime import datetime

class AgentType(str, Enum):
    ORCHESTRATOR = "orchestrator"
    INDUSTRY_ANALYST = "industry_analyst"
    DOCUMENT_INGESTION = "document_ingestion"
    LYNCH_PITCH = "lynch_pitch"
    MUNGER_INVERT = "munger_invert"
    EARNINGS_MONITOR = "earnings_monitor"
    KPI_TRACKER = "kpi_tracker"
    CITATION_ENFORCER = "citation_enforcer"

class LLMTier(str, Enum):
    PRIMARY = "primary"       # Claude Opus — complex reasoning
    SECONDARY = "secondary"   # GPT-4o — structured extraction
    LOCAL = "local"           # Llama 3.1 — air-gapped / cost control

class AgentMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: AgentType
    recipient: AgentType
    task_id: str
    coverage_id: str
    tenant_id: str
    payload: dict
    requires_citation: bool = True
    llm_preference: LLMTier = LLMTier.PRIMARY
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    parent_message_id: str | None = None

class AgentOutput(BaseModel):
    message_id: str
    agent: AgentType
    task_id: str
    coverage_id: str
    tenant_id: str
    content: str              # Markdown with inline citations
    citations: list[dict]     # list of Citation dicts
    citation_coverage_pct: float
    llm_used: str
    tokens_used: int
    latency_ms: int
    approved_by_enforcer: bool = False
    enforcer_status: str = "pending"  # pending / approved / partial / failed
    error: str | None = None

TASK 2 — Create packages/agents/shared/base_agent.py:
Abstract base class all agents inherit from:

import time
import litellm
from abc import ABC, abstractmethod
from packages.agents.shared.message import AgentMessage, AgentOutput, LLMTier
from packages.shared.config import settings

class BaseAgent(ABC):
    agent_type: AgentType  # must be set by subclass
    
    def __init__(self, db_session, retriever=None):
        self.db = db_session
        self.retriever = retriever
        self.litellm_base_url = settings.LITELLM_URL
        
    async def run(self, message: AgentMessage) -> AgentOutput:
        start = time.monotonic()
        try:
            result = await self._execute(message)
            latency_ms = int((time.monotonic() - start) * 1000)
            result.latency_ms = latency_ms
            await self._log_audit(message, result, "success")
            return result
        except Exception as e:
            latency_ms = int((time.monotonic() - start) * 1000)
            await self._log_audit(message, None, "error", str(e))
            raise
    
    @abstractmethod
    async def _execute(self, message: AgentMessage) -> AgentOutput:
        # Subclasses implement actual agent logic here
        pass
    
    async def _call_llm(self, messages: list[dict], tier: LLMTier, 
                         max_tokens: int = 4096, 
                         extended_thinking: bool = False) -> tuple[str, str, int]:
        # Call LiteLLM proxy with the specified tier
        # Returns: (content, model_name, total_tokens)
        # LiteLLM model names: "primary", "secondary", "local" (match config.yaml)
        model_name = tier.value  # "primary", "secondary", or "local"
        
        kwargs = {
            "model": model_name,
            "messages": messages,
            "max_tokens": max_tokens,
            "base_url": self.litellm_base_url,
        }
        
        if extended_thinking and tier == LLMTier.PRIMARY:
            # Add extended thinking for Claude (budget_tokens = 10000)
            kwargs["thinking"] = {"type": "enabled", "budget_tokens": 10000}
        
        response = await litellm.acompletion(**kwargs)
        content = response.choices[0].message.content
        model_used = response.model
        tokens = response.usage.total_tokens
        return content, model_used, tokens
    
    async def _log_audit(self, message: AgentMessage, result: AgentOutput | None,
                          status: str, error: str | None = None) -> None:
        # INSERT into agent_audit_log (append only):
        import hashlib, json
        from sqlalchemy import text
        input_hash = hashlib.sha256(json.dumps(message.payload, sort_keys=True).encode()).hexdigest()
        await self.db.execute(text("""
            INSERT INTO agent_audit_log 
            (id, tenant_id, coverage_id, agent_name, action, input_hash, output_id, 
             llm_used, tokens_used, latency_ms, created_at, metadata)
            VALUES (gen_random_uuid(), :tenant_id, :coverage_id, :agent_name, :action, 
                    :input_hash, :output_id, :llm_used, :tokens_used, :latency_ms, NOW(), :metadata::jsonb)
        """), {
            "tenant_id": message.tenant_id,
            "coverage_id": message.coverage_id,
            "agent_name": self.agent_type.value,
            "action": status,
            "input_hash": input_hash,
            "output_id": result.message_id if result else None,
            "llm_used": result.llm_used if result else None,
            "tokens_used": result.tokens_used if result else 0,
            "latency_ms": result.latency_ms if result else 0,
            "metadata": json.dumps({"error": error} if error else {}),
        })
        await self.db.commit()

TASK 3 — Create packages/agents/orchestrator/graph.py:
The LangGraph state machine for coverage workflow:

from langgraph.graph import StateGraph, END
from typing import TypedDict, Annotated
import operator

class CoverageState(TypedDict):
    coverage_id: str
    tenant_id: str
    user_intent: str            # what the user asked for
    current_step: str
    prerequisites_met: bool
    missing_prerequisites: list[str]
    industry_loaded: bool       # True if industry primer exists
    documents_loaded: bool      # True if ≥1 document indexed
    min_filings_present: bool   # True if ≥3 years of annual filings present
    lynch_pitch_complete: bool
    munger_invert_complete: bool
    quarterly_monitor_active: bool
    task_history: Annotated[list[dict], operator.add]  # append-only log
    output: dict | None         # final output from completed step
    error: str | None

def build_coverage_graph() -> StateGraph:
    graph = StateGraph(CoverageState)
    
    # Add nodes (each node is an async function)
    graph.add_node("coverage_init", coverage_init_node)
    graph.add_node("industry_analysis", industry_analysis_node)
    graph.add_node("doc_ingestion", doc_ingestion_node)
    graph.add_node("lynch_pitch", lynch_pitch_node)
    graph.add_node("munger_invert", munger_invert_node)
    graph.add_node("citation_validation", citation_validation_node)
    graph.add_node("quarterly_monitor", quarterly_monitor_node)
    graph.add_node("prerequisite_error", prerequisite_error_node)
    
    # Entry point
    graph.set_entry_point("coverage_init")
    
    # Routing from coverage_init based on user_intent
    graph.add_conditional_edges("coverage_init", route_from_init, {
        "industry": "industry_analysis",
        "ingest": "doc_ingestion",
        "lynch": "lynch_pitch",
        "munger": "munger_invert",
        "quarterly": "quarterly_monitor",
        "missing_prerequisites": "prerequisite_error",
    })
    
    # After industry analysis → doc_ingestion (user can continue workflow)
    graph.add_edge("industry_analysis", "citation_validation")
    
    # Lynch + Munger both go through citation_validation
    graph.add_edge("lynch_pitch", "citation_validation")
    graph.add_edge("munger_invert", "citation_validation")
    
    # Citation validation: approved → end, rejected → retry or partial
    graph.add_conditional_edges("citation_validation", route_citation_result, {
        "approved": END,
        "retry": "lynch_pitch",   # or "munger_invert" — determined by state.current_step
        "partial": END,           # surface PARTIAL flag to user
        "failed": END,            # max retries exceeded
    })
    
    graph.add_edge("doc_ingestion", END)
    graph.add_edge("quarterly_monitor", END)
    graph.add_edge("prerequisite_error", END)
    
    return graph.compile()

# Node functions (stubs — filled in by each agent's implementation):
async def coverage_init_node(state: CoverageState) -> CoverageState: ...
async def industry_analysis_node(state: CoverageState) -> CoverageState: ...
async def lynch_pitch_node(state: CoverageState) -> CoverageState: ...
async def munger_invert_node(state: CoverageState) -> CoverageState: ...
async def citation_validation_node(state: CoverageState) -> CoverageState: ...
async def quarterly_monitor_node(state: CoverageState) -> CoverageState: ...
async def prerequisite_error_node(state: CoverageState) -> CoverageState: ...

# Routing functions
def route_from_init(state: CoverageState) -> str:
    if not state["prerequisites_met"]:
        return "missing_prerequisites"
    # Map user_intent to node name
    intent_map = {"industry": "industry", "documents": "ingest",
                  "bull": "lynch", "bear": "munger", "quarterly": "quarterly"}
    return intent_map.get(state["user_intent"], "prerequisite_error")

def route_citation_result(state: CoverageState) -> str:
    output = state.get("output", {})
    enforcer_status = output.get("enforcer_status", "pending")
    retry_count = output.get("retry_count", 0)
    if enforcer_status == "approved":
        return "approved"
    elif retry_count < 3:
        return "retry"
    elif enforcer_status == "partial":
        return "partial"
    return "failed"

TASK 4 — Create packages/agents/orchestrator/tools.py:
Tool functions callable by the Orchestrator agent:

async def check_coverage_exists(coverage_id: str, tenant_id: str, db) -> bool:
    # Query coverages table with both IDs (RLS enforces tenant isolation)

async def check_industry_loaded(coverage_id: str, db) -> bool:
    # Query: join coverages → industries; check industries.primer_content IS NOT NULL

async def check_filing_count(coverage_id: str, form_type: str, min_years: int, db) -> dict:
    # Count documents of given form_type for coverage
    # Returns: {"count": int, "years_covered": list[str], "meets_minimum": bool}

async def list_available_agents() -> list[str]:
    return [t.value for t in AgentType if t != AgentType.ORCHESTRATOR]

async def dispatch_task(agent: str, skill: str, payload: dict, 
                        coverage_id: str, tenant_id: str, db) -> str:
    # INSERT into task_queue with status="queued"
    # Enqueue a Celery task: run_agent_task.delay(task_id, agent, skill, payload)
    # Return task_id

async def get_task_status(task_id: str, db) -> dict:
    # Query task_queue by task_id
    # Return status, started_at, completed_at, error

TASK 5 — Write unit tests tests/unit/test_langgraph_graph.py:
Using LangGraph's in-memory test utilities:
1. Build graph with build_coverage_graph()
2. Invoke with user_intent="bull", industry_loaded=False → routes to prerequisite_error
3. Invoke with user_intent="bull", documents_loaded=False → routes to prerequisite_error  
4. Invoke with user_intent="industry", all prerequisites met → routes to industry_analysis
5. citation_validation with enforcer_status="approved" → END
6. citation_validation with retry_count=2, enforcer_status="failed" → retry
7. citation_validation with retry_count=3, enforcer_status="failed" → END (max retries)

CONSTRAINTS:
- LangGraph requires LangSmith to be configured for tracing; set LANGCHAIN_TRACING_V2=true in env
- The CoverageState must be a TypedDict (not Pydantic) — LangGraph requires TypedDict
- The audit log INSERT must use parameterized queries — never f-string SQL
- BaseAgent._call_llm must not catch LLM exceptions — let them propagate to run() which logs them

ACCEPTANCE CRITERIA:
1. build_coverage_graph() compiles without errors
2. Unit tests for graph routing all pass
3. BaseAgent audit logging inserts a row to agent_audit_log on every run() call
4. AgentMessage serializes and deserializes cleanly via .model_dump() and .model_validate()
5. mypy packages/agents/shared/ packages/agents/orchestrator/ --strict passes
```

---

## PROMPT 2.2 — Citation Enforcer

```
You are implementing the Citation Enforcer for the Stock Analyst AI platform.
The BaseAgent, AgentMessage, HybridRetriever, and LangGraph graph are all in place.
Working directory: packages/agents/shared/

CONTEXT:
The Citation Enforcer is NOT a research agent — it is a validation gate that every agent output
must pass before it is stored or shown to users. It enforces the system's core invariant:
every factual claim must be traceable to an exact retrievable quote.

The 6 validation checks must all pass for an output to be approved:
1. Citation coverage ≥ 95% (at least 95% of factual claims have citations)
2. Citation format valid: [Document Name, Section]: "exact quote"
3. Every exact quote is findable in Qdrant via BM25 search (hallucination check)
4. No unsourced numbers (all numeric values followed by a citation)
5. No future speculation ("will", "expects to") unless it's a direct management quote citation
6. Inferences explicitly labeled as (inferred from [source])

TASK 1 — Create packages/agents/shared/citation_enforcer.py:

import re
from dataclasses import dataclass
from packages.rag.retrieval.hybrid_retriever import HybridRetriever

@dataclass
class CheckResult:
    check_name: str
    passed: bool
    details: str
    failed_items: list[str]  # specific items that failed, for retry prompt

@dataclass
class ValidationResult:
    approved: bool
    enforcer_status: str  # "approved", "partial", "failed"
    failed_checks: list[CheckResult]
    citation_coverage_pct: float
    retry_prompt: str | None  # actionable instructions for the agent to fix failures
    hallucination_count: int  # number of quotes not found in RAG

# Regex patterns
CITATION_PATTERN = re.compile(
    r'\[([^\]]+),\s*([^\]]+)\]:\s*"([^"]{10,})"',  # [Doc, Section]: "quote (min 10 chars)"
    re.MULTILINE
)
NUMBER_PATTERN = re.compile(
    r'(?<!\[)\b\d[\d,]*\.?\d*\s*(?:billion|million|thousand|%|percent|B|M|K)\b',
    re.IGNORECASE
)
SPECULATION_PATTERN = re.compile(
    r'\b(?:will\s+(?:grow|increase|decrease|improve|expand|reach)|'
    r'expects?\s+to|expected\s+to|is\s+expected\s+to|'
    r'analysts\s+predict|forecasts?|projects?)\b',
    re.IGNORECASE
)
INFERENCE_PATTERN = re.compile(
    r'\b(?:appears?\s+to|seems?\s+to|likely|probably|presumably|'
    r'suggests?\s+that|implies?\s+that)\b',
    re.IGNORECASE
)

class CitationEnforcer:
    def __init__(self, retriever: HybridRetriever):
        self.retriever = retriever
    
    async def validate(self, output: AgentOutput, 
                       tenant_id: str, coverage_id: str) -> ValidationResult:
        content = output.content
        checks = []
        
        # Run all 6 checks
        checks.append(self._check_citation_coverage(content))
        checks.append(self._check_quote_format(content))
        checks.append(await self._check_quotes_exist_in_rag(content, tenant_id, coverage_id))
        checks.append(self._check_no_unsourced_numbers(content))
        checks.append(self._check_no_future_speculation(content))
        checks.append(self._check_inference_labeling(content))
        
        all_passed = all(c.passed for c in checks)
        citation_cov = self._compute_citation_coverage(content)
        hallucination_check = next((c for c in checks if c.check_name == "quote_exists_in_rag"), None)
        hallucination_count = len(hallucination_check.failed_items) if hallucination_check else 0
        
        if all_passed:
            status = "approved"
        elif citation_cov >= 0.80:  # close but not perfect → partial
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
    
    def _check_citation_coverage(self, content: str) -> CheckResult:
        # Count sentences (split on ". " or ".\n") that make factual claims
        # A factual claim: sentence contains a number, proper noun, or declarative statement
        # Count how many such sentences have a citation in the same paragraph
        # Coverage = cited_claims / total_claims
        # Target ≥ 0.95
        citations_found = CITATION_PATTERN.findall(content)
        
        # Heuristic for claim count: count paragraphs with declarative statements
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        claim_paragraphs = [p for p in paragraphs if any(c.isdigit() for c in p) 
                           or re.search(r'\b(?:is|are|was|were|has|have|had)\b', p)]
        cited_paragraphs = [p for p in claim_paragraphs if CITATION_PATTERN.search(p)]
        
        coverage = len(cited_paragraphs) / max(len(claim_paragraphs), 1)
        passed = coverage >= 0.95
        
        return CheckResult(
            check_name="citation_coverage",
            passed=passed,
            details=f"Citation coverage: {coverage:.1%} (need ≥95%)",
            failed_items=[f"Paragraph {i+1} has no citation" 
                         for i, p in enumerate(claim_paragraphs) if p not in cited_paragraphs]
        )
    
    def _check_quote_format(self, content: str) -> CheckResult:
        # Find all citation-like patterns
        # Any [text, text]: "text" that doesn't match the strict pattern is a format violation
        # Also detect citations missing the section part: [Doc]: "quote" (wrong — needs section)
        loose_citations = re.findall(r'\[[^\]]+\]:\s*"[^"]+"', content)
        strict_citations = CITATION_PATTERN.findall(content)
        
        malformed = [c for c in loose_citations 
                    if not CITATION_PATTERN.search(f'[{c.split("]")[0][1:]}]')]
        
        passed = len(malformed) == 0
        return CheckResult(
            check_name="quote_format",
            passed=passed,
            details=f"Found {len(malformed)} malformed citations (need [Doc, Section]: \"quote\")",
            failed_items=malformed[:5]  # show first 5
        )
    
    async def _check_quotes_exist_in_rag(self, content: str, 
                                          tenant_id: str, coverage_id: str) -> CheckResult:
        # For each citation, BM25-search for the exact quote text
        # If not found in Qdrant → hallucination detected
        citations = CITATION_PATTERN.findall(content)  # (doc, section, quote)
        not_found = []
        
        for doc, section, quote in citations:
            result = await self.retriever.retrieve_exact_quote(
                quote=quote.strip(),
                tenant_id=tenant_id,
                coverage_id=coverage_id
            )
            if result is None:
                not_found.append(f'"{quote[:60]}..."')
        
        passed = len(not_found) == 0
        return CheckResult(
            check_name="quote_exists_in_rag",
            passed=passed,
            details=f"{len(not_found)} quotes not found in document store (potential hallucinations)",
            failed_items=not_found[:5]
        )
    
    def _check_no_unsourced_numbers(self, content: str) -> CheckResult:
        # Find all financial numbers in text
        # Check each: within the same sentence or next sentence, is there a citation?
        sentences = re.split(r'(?<=[.!?])\s+', content)
        unsourced = []
        
        for i, sentence in enumerate(sentences):
            numbers = NUMBER_PATTERN.findall(sentence)
            if numbers:
                # Check if this sentence or the next has a citation
                context = sentence + (" " + sentences[i+1] if i+1 < len(sentences) else "")
                if not CITATION_PATTERN.search(context):
                    unsourced.extend([f'"{n}" in: "{sentence[:80]}"' for n in numbers])
        
        passed = len(unsourced) == 0
        return CheckResult(
            check_name="no_unsourced_numbers",
            passed=passed,
            details=f"{len(unsourced)} numbers found without adjacent citations",
            failed_items=unsourced[:5]
        )
    
    def _check_no_future_speculation(self, content: str) -> CheckResult:
        # Find speculation phrases not immediately followed by a citation
        sentences = re.split(r'(?<=[.!?])\s+', content)
        violations = []
        
        for sentence in sentences:
            if SPECULATION_PATTERN.search(sentence):
                if not CITATION_PATTERN.search(sentence):
                    violations.append(sentence[:100])
        
        passed = len(violations) == 0
        return CheckResult(
            check_name="no_future_speculation",
            passed=passed,
            details=f"{len(violations)} speculative statements without source citation",
            failed_items=violations[:3]
        )
    
    def _check_inference_labeling(self, content: str) -> CheckResult:
        # Find inference language not marked with (inferred from [source])
        sentences = re.split(r'(?<=[.!?])\s+', content)
        unlabeled = []
        
        for sentence in sentences:
            if INFERENCE_PATTERN.search(sentence):
                if "(inferred from" not in sentence.lower():
                    unlabeled.append(sentence[:100])
        
        passed = len(unlabeled) == 0
        return CheckResult(
            check_name="inference_labeling",
            passed=passed,
            details=f"{len(unlabeled)} inferred statements not labeled with (inferred from [source])",
            failed_items=unlabeled[:3]
        )
    
    def _compute_citation_coverage(self, content: str) -> float:
        # Same logic as _check_citation_coverage but just returns the float
        paragraphs = [p.strip() for p in content.split('\n\n') if p.strip()]
        claim_paragraphs = [p for p in paragraphs if any(c.isdigit() for c in p)]
        cited = [p for p in claim_paragraphs if CITATION_PATTERN.search(p)]
        return len(cited) / max(len(claim_paragraphs), 1)
    
    def _build_retry_prompt(self, checks: list[CheckResult], original_content: str) -> str:
        # Build a specific, actionable prompt telling the agent exactly what to fix
        lines = [
            "Your previous output FAILED citation validation. Fix the following issues and rewrite:",
            ""
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
        
        lines.extend([
            "RULES TO FOLLOW:",
            "1. Every factual claim needs: [Document Name, Section]: \"exact quote\" → interpretation",
            "2. Every number needs a citation in the same or next sentence",
            "3. Exact quotes must appear verbatim in the source documents — do not paraphrase",
            "4. Replace 'will grow/increase/expects to' with sourced management quotes or remove",
            "5. Mark inferences: '(inferred from [Document Name, Section])'",
            "",
            "Rewrite the full output following these rules exactly."
        ])
        return "\n".join(lines)

TASK 2 — Integrate CitationEnforcer into the LangGraph citation_validation node:
In packages/agents/orchestrator/graph.py, implement the citation_validation_node:

async def citation_validation_node(state: CoverageState) -> CoverageState:
    output = state["output"]
    retry_count = output.get("retry_count", 0)
    
    enforcer = CitationEnforcer(retriever=get_retriever())
    result = await enforcer.validate(
        output=AgentOutput(**output),
        tenant_id=state["tenant_id"],
        coverage_id=state["coverage_id"]
    )
    
    # Update output with enforcement result
    updated_output = {**output,
        "approved_by_enforcer": result.approved,
        "enforcer_status": result.enforcer_status,
        "citation_coverage_pct": result.citation_coverage_pct,
        "retry_prompt": result.retry_prompt,
        "retry_count": retry_count + (0 if result.approved else 1),
        "hallucination_count": result.hallucination_count,
    }
    
    return {**state, "output": updated_output}

TASK 3 — Write comprehensive unit tests tests/unit/test_citation_enforcer.py:
Mock the HybridRetriever.retrieve_exact_quote to control what's "found":

Test cases for each check:

check_citation_coverage:
1. Content with 100% cited paragraphs → passed=True
2. Content with 80% cited paragraphs → passed=False, coverage=0.8
3. Content with only non-claim paragraphs (no numbers, pure headers) → passed=True

check_quote_format:
4. '[AAPL 10-K 2023, Business]: "Revenue was $383.3 billion"' → passed=True
5. '[AAPL 10-K 2023]: "Revenue was $383.3 billion"' (missing section) → passed=False
6. 'AAPL 10-K 2023: "Revenue was $383.3 billion"' (no brackets) → passed=False

check_quotes_exist_in_rag:
7. Quote found in retriever → passed=True
8. Quote NOT found in retriever → passed=False, failed_items has the quote
9. 3 quotes: 2 found, 1 not found → passed=False, hallucination_count=1

check_no_unsourced_numbers:
10. "Revenue was $383.3 billion [AAPL, Business]: 'Revenue was $383.3 billion'" → passed=True
11. "Revenue was $383.3 billion in FY2023." (no citation) → passed=False
12. Non-financial numbers ("The company has 5 divisions") → should not trigger (too small)

check_no_future_speculation:
13. "Management expects revenue to grow" without citation → passed=False
14. "Management expects revenue to grow [Transcript, Q4]: 'We expect revenues to grow'" → passed=True
15. "Revenue grew 12% in 2023" (past tense) → passed=True

check_inference_labeling:
16. "The company appears to be losing market share (inferred from [10-K, MD&A])" → passed=True
17. "The company appears to be losing market share" (no labeling) → passed=False

_build_retry_prompt:
18. Failed on 2 checks → retry_prompt contains both check names and specific failed items
19. Retry prompt contains the 5 rules to follow

CONSTRAINTS:
- The regex patterns must handle multi-line content (use re.MULTILINE and re.DOTALL where needed)
- _check_quotes_exist_in_rag is async (it calls the retriever) — all 6 checks must be awaitable or run in await
- Never mutate the original AgentOutput — create a new dict/object with updated fields
- The retry prompt must be specific enough that an LLM can act on it — not generic instructions

ACCEPTANCE CRITERIA:
1. All 19 unit tests pass
2. CitationEnforcer rejects a deliberately hallucinated output (quote not in RAG) → approved=False
3. CitationEnforcer approves a clean, fully-cited output → approved=True, status="approved"
4. citation_validation_node in LangGraph correctly updates state.output with enforcer results
5. After 3 failed retries in the graph, route_citation_result returns "failed"
```

---

## PROMPT 2.3 — Orchestrator Agent

```
You are implementing the Orchestrator Agent for the Stock Analyst AI platform.
The LangGraph graph, BaseAgent, AgentMessage, and CitationEnforcer are all in place.
Working directory: packages/agents/orchestrator/

CONTEXT:
The Orchestrator never generates research. It only plans, routes, and monitors.
Every user request goes through the Orchestrator first. It checks prerequisites,
builds a task plan, and dispatches to specialist agents. It always returns structured JSON.

TASK 1 — Create packages/agents/orchestrator/agent.py:
Implement OrchestratorAgent extending BaseAgent.

System prompt (embed as a constant, not an f-string — no user input in the prompt):

ORCHESTRATOR_SYSTEM_PROMPT = """
You are the Orchestrator for a professional equity research platform.
Your ONLY job is to plan, route, and monitor — never generate research yourself.

ROUTING RULES:
- "industry overview", "industry analysis", "what industry is this" → IndustryAnalystAgent
- "fetch filings", "upload document", "get 10-K" → DocumentIngestionAgent
- "why own", "bull case", "Lynch pitch", "why invest" → LynchPitchAgent
- "why not own", "bear case", "Munger invert", "risks", "how could I lose" → MungerInvertAgent
- "earnings", "quarterly update", "new 10-Q", "guidance vs results" → EarningsMonitorAgent
- "KPIs", "metrics", "revenue trend", "time series" → KPITrackerAgent

PLANNING RULES:
1. Always check if the coverage (stock project) exists before routing.
2. Always check if industry fundamentals are loaded before allowing research agents.
3. Always check if minimum 3 years of annual filings are present before Bull/Bear cases.
4. If ANY prerequisite is missing: return PREREQUISITE_MISSING with exact instructions.

OUTPUT FORMAT — always return valid JSON, nothing else:
{
  "plan_id": "<uuid>",
  "intent_detected": "<what the user wants>",
  "steps": [
    {"step": 1, "agent": "<AgentType>", "skill": "<skill_name>", "input": {}}
  ],
  "estimated_duration_seconds": <int>,
  "prerequisites_met": <bool>,
  "missing_prerequisites": ["<description of what's missing>"],
  "routing_confidence": <float 0-1>
}

If prerequisites are NOT met, return:
{
  "plan_id": "<uuid>",
  "intent_detected": "<what the user wants>",
  "steps": [],
  "estimated_duration_seconds": 0,
  "prerequisites_met": false,
  "missing_prerequisites": ["<specific missing item>"],
  "routing_confidence": 1.0
}
"""

class OrchestratorAgent(BaseAgent):
    agent_type = AgentType.ORCHESTRATOR
    
    async def _execute(self, message: AgentMessage) -> AgentOutput:
        # Step 1: check prerequisites using tool functions
        prereqs = await self._check_prerequisites(message)
        
        # Step 2: build messages for LLM
        messages = [
            {"role": "system", "content": ORCHESTRATOR_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps({
                "user_request": message.payload.get("user_request", ""),
                "coverage_id": message.coverage_id,
                "prerequisites_status": prereqs,
            })}
        ]
        
        # Step 3: call LLM (use SECONDARY tier — orchestration doesn't need Opus)
        content, model_used, tokens = await self._call_llm(
            messages=messages,
            tier=LLMTier.SECONDARY,
            max_tokens=1024
        )
        
        # Step 4: parse and validate JSON response
        try:
            plan = json.loads(content)
        except json.JSONDecodeError:
            # Extract JSON from response if it contains extra text
            match = re.search(r'\{.*\}', content, re.DOTALL)
            if match:
                plan = json.loads(match.group())
            else:
                raise ValueError(f"Orchestrator returned non-JSON response: {content[:200]}")
        
        # Step 5: if prerequisites met, dispatch first step
        dispatched_task_id = None
        if plan.get("prerequisites_met") and plan.get("steps"):
            first_step = plan["steps"][0]
            dispatched_task_id = await dispatch_task(
                agent=first_step["agent"],
                skill=first_step["skill"],
                payload={**first_step["input"], "original_request": message.payload},
                coverage_id=message.coverage_id,
                tenant_id=message.tenant_id,
                db=self.db
            )
            plan["dispatched_task_id"] = dispatched_task_id
        
        return AgentOutput(
            message_id=str(uuid.uuid4()),
            agent=AgentType.ORCHESTRATOR,
            task_id=message.task_id,
            coverage_id=message.coverage_id,
            tenant_id=message.tenant_id,
            content=json.dumps(plan, indent=2),
            citations=[],
            citation_coverage_pct=1.0,  # Orchestrator doesn't cite — skip enforcer
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,
            approved_by_enforcer=True,  # Orchestrator outputs are plans, not research
            enforcer_status="approved",
        )
    
    async def _check_prerequisites(self, message: AgentMessage) -> dict:
        coverage_id = message.coverage_id
        tenant_id = message.tenant_id
        
        exists = await check_coverage_exists(coverage_id, tenant_id, self.db)
        industry_loaded = await check_industry_loaded(coverage_id, self.db) if exists else False
        filing_status = await check_filing_count(coverage_id, "10-K", 3, self.db) if exists else {}
        
        return {
            "coverage_exists": exists,
            "industry_loaded": industry_loaded,
            "annual_filings": filing_status.get("count", 0),
            "annual_filings_years": filing_status.get("years_covered", []),
            "min_filings_met": filing_status.get("meets_minimum", False),
        }

TASK 2 — Implement the agent task runner Celery task apps/api/tasks/agent_runner.py:

@celery_app.task(bind=True, max_retries=1)
def run_agent_task(self, task_id: str, agent_name: str, skill: str, payload: dict):
    # This runs specialist agents from Celery worker context
    # 1. Load task from task_queue, update status to "running"
    # 2. Load coverage + tenant context from task record
    # 3. Instantiate the correct agent based on agent_name:
    #    agent_map = {"orchestrator": OrchestratorAgent, "lynch_pitch": LynchPitchAgent, ...}
    # 4. Build AgentMessage from task record
    # 5. await agent.run(message) — use asyncio.run() since Celery is sync
    # 6. If agent output approved_by_enforcer: save to research_outputs table
    # 7. Update task_queue: status="completed", completed_at=now(), result=output dict
    # On error: update task status to "failed", set error message

TASK 3 — Add Orchestrator endpoint to apps/api/routers/tasks.py:
POST /api/v1/coverages/{coverage_id}/orchestrate:
  Body: {"user_request": "Run a bull case for AAPL"}
  Auth: analyst role minimum
  Processing:
    - Build AgentMessage for Orchestrator
    - Call OrchestratorAgent directly (synchronous, fast — it doesn't do heavy work)
    - Return the plan JSON immediately (don't queue — the Orchestrator is fast)
  Response: 200 with the plan JSON

TASK 4 — Write unit tests tests/unit/test_orchestrator_agent.py:
Mock the tool functions and LLM call:

1. Valid request "run bull case" with all prerequisites met → plan has "lynch_pitch" in steps[0].agent
2. Valid request "run bear case" → plan has "munger_invert" in steps[0].agent
3. Request with missing industry → prerequisites_met=False, missing_prerequisites describes industry
4. Request with <3 annual filings → prerequisites_met=False, missing_prerequisites describes filings
5. LLM returns malformed JSON → ValueError raised (not silently swallowed)
6. LLM returns JSON wrapped in markdown code block → extracted and parsed correctly
7. Dispatched task: run_agent_task.delay is called with correct agent name

CONSTRAINTS:
- The Orchestrator must NOT include any financial analysis in its output — only routing metadata
- JSON output validation: the plan must be parseable; if not, retry once with a repair prompt before raising
- The Orchestrator skips Citation Enforcer (its outputs are plans, not research claims)
- run_agent_task must handle agent import errors gracefully (unknown agent_name → task fails with clear error)

ACCEPTANCE CRITERIA:
1. POST /orchestrate with "run bull case for AAPL" (all prereqs met) → 200 with plan JSON containing lynch_pitch
2. POST /orchestrate with "run bull case" but 0 filings → prerequisites_met=false, explains what's needed
3. All 7 unit tests pass
4. OrchestratorAgent logs to agent_audit_log on every call (verified in integration test)
```

---

## PROMPT 2.4 — Industry Analyst Agent

```
You are implementing the Industry Analyst Agent for the Stock Analyst AI platform.
The BaseAgent, CitationEnforcer, OrchestratorAgent, and LangGraph graph are all in place.
Working directory: packages/agents/industry_analyst/

CONTEXT:
The Industry Analyst Agent produces the Step 2 industry primer — a structured, source-cited
overview of the industry that underpins all stock research in that sector. It runs ONCE per
industry (shared across all tenants) and its output is reused for every stock in that industry.
It uses extended thinking (Claude) for deep synthesis and Tavily for web research.

TASK 1 — Create packages/agents/industry_analyst/prompts.py:
Store the system prompt as a constant (do not use f-strings or dynamic insertion):

INDUSTRY_ANALYST_SYSTEM_PROMPT = """
You are a senior industry analyst writing for long-term equity investors.
You produce factual, structured industry overviews — no opinions, no hype, no forecasts without mechanisms.

EVIDENCE DISCIPLINE:
- If using uploaded documents: cite [Document Name, Section]: "exact quote"
- If using web research: cite [Source Name, URL, Date]: "exact quote"
- If a claim is inferred, mark it: (inferred from [source])
- If a claim cannot be sourced: write "(unknown — not found in available sources)"
- NEVER state an unsourced claim as fact.

MANDATORY OUTPUT STRUCTURE — 6 sections + synthesis. Use these exact section headers:
## 1. Industry Purpose & Core Economics
## 2. Industry Structure & Competitive Shape
## 3. Demand & Growth Drivers
## 4. Supply Side, Cost Structure & Constraints
## 5. Technology, Regulation & Structural Change
## 6. Medium-Term Outlook (5–10 Years)

## Investor Synthesis
Five bullets (each ≤ 2 sentences), covering EXACTLY:
- Core economic engine
- Primary growth lever
- Structural constraint investors underestimate
- Key risk that could change trajectory
- What kind of companies tend to win in this industry

TARGET LENGTH: 1,200–1,800 words total. Dense, no filler, no repetition.

Before writing, use your research tools to gather evidence. Then write the full output in one response.
"""

TASK 2 — Create packages/agents/industry_analyst/tools.py:
Tool functions for web research and saving the primer:

async def web_search(query: str, max_results: int = 5) -> list[dict]:
    # Call Tavily API: POST https://api.tavily.com/search
    # Body: {"api_key": settings.TAVILY_API_KEY, "query": query, "max_results": max_results,
    #        "search_depth": "advanced", "include_answer": false}
    # Returns list of: {"title": str, "url": str, "published_date": str, "content": str}
    # Raise ValueError if TAVILY_API_KEY not configured

async def fetch_url(url: str) -> str:
    # Fetch URL content (for PDFs from regulator/industry body sites)
    # IMPORTANT: only allow these domains to prevent SSRF:
    #   sec.gov, bis.org, imf.org, worldbank.org, oecd.org, federalreserve.gov,
    #   statista.com, mckinsey.com, bain.com, deloitte.com, pwc.com, bcg.com
    # Raise ValueError for any other domain
    # Use httpx; extract text from HTML using BeautifulSoup; truncate to 5000 chars
    ALLOWED_DOMAINS = {"sec.gov", "bis.org", "imf.org", "worldbank.org", "oecd.org", 
                       "federalreserve.gov", "statista.com", "mckinsey.com", "bain.com",
                       "deloitte.com", "pwc.com", "bcg.com"}
    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lstrip("www.")
    if not any(url.endswith(d) or domain == d for d in ALLOWED_DOMAINS):
        raise ValueError(f"Domain not in allowlist: {domain}")

async def rag_search_industry(query: str, industry_id: str) -> list[dict]:
    # Search uploaded industry documents (scoped to industry, not coverage)
    # This is a RAG search without coverage_id filter — searches across all docs tagged to this industry
    # Returns list of chunk dicts with content + metadata

async def save_industry_primer(industry_id: str, content: str, 
                                citations: list[dict], llm_used: str, db) -> str:
    # UPDATE industries SET primer_content=content, primer_citations=citations,
    #   word_count=len(content.split()), llm_used=llm_used, updated_at=now()
    # WHERE id=industry_id
    # Return industry_id

TASK 3 — Create packages/agents/industry_analyst/schemas.py:
Output schema for the industry primer:

class IndustryPrimerSection(BaseModel):
    section_number: int
    section_name: str
    content: str
    citations: list[dict]
    word_count: int

class InvestorSynthesisBullet(BaseModel):
    topic: str  # "core_economic_engine", "primary_growth_lever", etc.
    content: str
    citations: list[dict]

class IndustryPrimer(BaseModel):
    industry_id: str
    industry_name: str
    sections: list[IndustryPrimerSection]  # 6 sections
    investor_synthesis: list[InvestorSynthesisBullet]  # exactly 5 bullets
    all_citations: list[dict]
    word_count: int
    llm_used: str
    created_at: datetime
    confidence_score: float  # 0-1: (cited_claims / total_claims)
    
    @model_validator(mode='after')
    def validate_structure(self):
        assert len(self.sections) == 6, "Must have exactly 6 sections"
        assert len(self.investor_synthesis) == 5, "Must have exactly 5 synthesis bullets"
        assert 1200 <= self.word_count <= 2000, f"Word count {self.word_count} outside 1200-1800 range"
        return self

TASK 4 — Create packages/agents/industry_analyst/agent.py:
Implement IndustryAnalystAgent extending BaseAgent:

class IndustryAnalystAgent(BaseAgent):
    agent_type = AgentType.INDUSTRY_ANALYST
    
    async def _execute(self, message: AgentMessage) -> AgentOutput:
        industry_name = message.payload["industry_name"]
        industry_id = message.payload["industry_id"]
        
        # Step 1: Gather research (up to 3 web searches + optional URL fetches)
        research_context = await self._gather_research(industry_name, industry_id)
        
        # Step 2: Build prompt with research context
        messages = [
            {"role": "system", "content": INDUSTRY_ANALYST_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_message(industry_name, research_context)}
        ]
        
        # Step 3: Call PRIMARY LLM with extended thinking
        content, model_used, tokens = await self._call_llm(
            messages=messages,
            tier=LLMTier.PRIMARY,
            max_tokens=8000,
            extended_thinking=True
        )
        
        # Step 4: Parse and validate structure
        primer = self._parse_primer_output(content, industry_id, industry_name, model_used)
        
        # Step 5: Save to industries table
        await save_industry_primer(industry_id, content, primer.all_citations, model_used, self.db)
        
        return AgentOutput(
            message_id=str(uuid.uuid4()),
            agent=AgentType.INDUSTRY_ANALYST,
            task_id=message.task_id,
            coverage_id=message.coverage_id,
            tenant_id=message.tenant_id,
            content=content,
            citations=primer.all_citations,
            citation_coverage_pct=primer.confidence_score,
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,
        )
    
    async def _gather_research(self, industry_name: str, industry_id: str) -> str:
        # Run 3 targeted searches and compile into a research brief
        queries = [
            f"{industry_name} industry economics business model revenue drivers",
            f"{industry_name} industry competitive landscape major players market structure",
            f"{industry_name} industry regulatory environment technology trends outlook"
        ]
        results = []
        for q in queries:
            search_results = await web_search(q, max_results=4)
            results.extend(search_results)
        
        # Format as a structured context block for the LLM
        context_parts = ["=== WEB RESEARCH CONTEXT ===\n"]
        for r in results[:10]:  # cap at 10 results
            context_parts.append(
                f"SOURCE: [{r['title']}, {r['url']}, {r.get('published_date', 'n/d')}]\n"
                f"CONTENT: {r['content'][:1000]}\n"
            )
        return "\n".join(context_parts)
    
    def _build_user_message(self, industry_name: str, research_context: str) -> str:
        return (
            f"Write a comprehensive industry primer for: {industry_name}\n\n"
            f"Use the following research as your primary evidence base. "
            f"Cite every claim using [Source Name, URL, Date]: \"exact quote\" format.\n\n"
            f"{research_context}"
        )
    
    def _parse_primer_output(self, content: str, industry_id: str, 
                              industry_name: str, llm_used: str) -> IndustryPrimer:
        # Extract sections using ## header detection
        # Extract all citations using CITATION_PATTERN
        # Compute confidence_score
        # Build and validate IndustryPrimer (pydantic validation will catch structural errors)
        from packages.agents.shared.citation_enforcer import CITATION_PATTERN
        
        citations = [{"doc": d, "section": s, "quote": q} 
                    for d, s, q in CITATION_PATTERN.findall(content)]
        
        sections = self._extract_sections(content)
        synthesis = self._extract_synthesis(content)
        word_count = len(content.split())
        
        total_paragraphs = len([p for p in content.split('\n\n') if p.strip()])
        cited_paragraphs = len([p for p in content.split('\n\n') 
                                if p.strip() and CITATION_PATTERN.search(p)])
        confidence = cited_paragraphs / max(total_paragraphs, 1)
        
        return IndustryPrimer(
            industry_id=industry_id,
            industry_name=industry_name,
            sections=sections,
            investor_synthesis=synthesis,
            all_citations=citations,
            word_count=word_count,
            llm_used=llm_used,
            created_at=datetime.utcnow(),
            confidence_score=confidence,
        )
    
    def _extract_sections(self, content: str) -> list[IndustryPrimerSection]:
        # Parse markdown: find ## 1., ## 2., etc. headers and extract content between them
        # Return 6 IndustryPrimerSection objects
        ...
    
    def _extract_synthesis(self, content: str) -> list[InvestorSynthesisBullet]:
        # Find ## Investor Synthesis section
        # Extract the 5 bullet points (lines starting with -)
        # Map to the 5 expected topics
        ...

TASK 5 — Create the industry primer API endpoint and UI page:
In apps/api/routers/tasks.py, add:
POST /api/v1/coverages/{coverage_id}/tasks/industry-analysis:
  Body: {"industry_name": "Enterprise Software"}
  Auth: analyst minimum
  Behavior: dispatch to IndustryAnalystAgent via Celery
  Response: 202 with task_id

In apps/web/app/(protected)/coverages/[id]/research/industry/page.tsx:
- If industry primer exists: render the 6 sections with citation tooltips and investor synthesis
- If not: show "Run Industry Analysis" button → POST to task endpoint → poll task status
- Citation tooltip component: hover over [Src, Section] citation → popover shows full quote
- Section jump nav: sidebar list of the 6 sections → smooth scroll to anchor

TASK 6 — Write unit tests tests/unit/test_industry_analyst.py:
Mock web_search to return fake but structured results; mock LLM to return a valid primer:
1. _gather_research makes exactly 3 web search calls
2. _build_user_message includes the industry name and research context
3. _parse_primer_output on a valid 6-section output returns IndustryPrimer with all fields
4. _parse_primer_output raises ValidationError if sections < 6
5. _parse_primer_output raises ValidationError if word_count < 1200
6. fetch_url with allowed domain → returns content
7. fetch_url with disallowed domain → raises ValueError
8. Web search timeout → error propagates (not silently swallowed)

CONSTRAINTS:
- The SSRF protection in fetch_url is a security requirement — do not bypass it
- Extended thinking requires the LLM tier to be PRIMARY (Claude); if tier is LOCAL, skip extended thinking
- Industry primers are NOT tenant-scoped: stored in the industries table without tenant_id
- The IndustryPrimer pydantic model validator must fail loudly if the LLM didn't follow the structure
  so the agent can retry with a corrective prompt

ACCEPTANCE CRITERIA:
1. POST /tasks/industry-analysis for "Enterprise Software" → task completes → industry primer in DB
2. GET /research/industry shows the primer with all 6 sections rendered
3. Citation tooltips appear on hover
4. IndustryPrimer validator rejects output with <6 sections
5. fetch_url rejects non-allowlisted domains with ValueError
6. All 8 unit tests pass
```

---

## PROMPT 2.5 — Lynch Pitch Agent (Bull Case)

```
You are implementing the Lynch Pitch Agent for the Stock Analyst AI platform.
The BaseAgent, CitationEnforcer, OrchestratorAgent, HybridRetriever, and LangGraph graph are in place.
Working directory: packages/agents/lynch_pitch/

CONTEXT:
The Lynch Pitch Agent answers "why would I own this stock?" using exactly 8 structured questions
in the style of Peter Lynch: simple language, plain English, grounded entirely in company filings.
It can ONLY use documents in the coverage's knowledge base — no external information.
Every factual claim requires an exact quote. If no quote is found, it writes "Not found in uploaded documents."

TASK 1 — Create packages/agents/lynch_pitch/prompts.py:

LYNCH_PITCH_SYSTEM_PROMPT = """
You are a long-term equity analyst writing in the style of Peter Lynch.
You produce SHORT, PLAIN, SOURCE-DISCIPLINED investment pitches.

ABSOLUTE RULES:
1. USE ONLY documents in this coverage's knowledge base. No external knowledge, no memory of the company.
2. For EVERY factual claim or metric, provide the exact quote FIRST, then interpretation:
   Format: [Document Name, Page/Section]: "exact quote" → your interpretation
3. If you cannot find a supporting quote: write "Not found in uploaded documents." — do NOT guess.
4. No buzzwords. No macro speculation. No DCF or valuation models.
5. Plain English. Short sentences. A smart teenager should understand this.
6. Never use: "exciting opportunity", "compelling", "robust", "synergies", "value creation"

ANSWER THESE 8 QUESTIONS IN ORDER:
Use the exact question headings below. Each answer must cite at least one source.

### Q1: What does this company do?
One sentence. What product/service do they sell, to whom, and how do they make money?

### Q2: What is the single reason this stock could work?
ONE idea only. Not three ideas — one. State it plainly.

### Q3: How does the company make money?
Revenue model and margins. Include gross margin %, operating margin if available.

### Q4: Balance sheet health
State: total debt, cash/equivalents, free cash flow. State the period for each figure.

### Q5: What type of company is this?
Choose exactly one: slow grower / stalwart / fast grower / cyclical / turnaround / asset play
One sentence of justification.

### Q6: What could go wrong?
Be honest. This makes the pitch credible. What are the 2-3 most realistic risks?

### Q7: Why might the market be mispricing this?
What does the market misunderstand or undervalue?

### Q8: Bottom line
3-4 sentences: why it's interesting, what must go right, what would prove you wrong.

CITATION FORMAT: [Document Name, Page/Section]: "exact quote from that document" → interpretation
"""

TASK 2 — Create packages/agents/lynch_pitch/schemas.py:

from enum import Enum

class CompanyType(str, Enum):
    SLOW_GROWER = "slow_grower"
    STALWART = "stalwart"
    FAST_GROWER = "fast_grower"
    CYCLICAL = "cyclical"
    TURNAROUND = "turnaround"
    ASSET_PLAY = "asset_play"

class AnswerWithCitation(BaseModel):
    question_number: int
    question_text: str
    answer_text: str
    citations: list[dict]
    citation_coverage_pct: float
    not_found_items: list[str]  # items where agent said "Not found in uploaded documents"
    
    @model_validator(mode='after')
    def require_citation_or_not_found(self):
        has_content = bool(self.answer_text.strip())
        all_not_found = all("not found" in item.lower() for item in self.not_found_items) if self.not_found_items else False
        # Each answer must either have a citation OR explicitly say "Not found"
        if has_content and self.citation_coverage_pct < 0.5 and not self.not_found_items:
            raise ValueError(f"Q{self.question_number} has content but no citations or Not Found declarations")
        return self

class LynchPitch(BaseModel):
    coverage_id: str
    company_name: str
    ticker: str
    answers: list[AnswerWithCitation]  # exactly 8
    company_type: CompanyType
    all_citations: list[dict]
    citation_coverage_pct: float
    word_count: int
    generated_at: datetime
    llm_used: str
    
    @model_validator(mode='after')
    def validate_all_8_questions(self):
        assert len(self.answers) == 8, f"Must answer all 8 questions, got {len(self.answers)}"
        assert self.citation_coverage_pct >= 0.90, (
            f"Citation coverage {self.citation_coverage_pct:.1%} too low — minimum 90% for storage "
            "(Citation Enforcer will enforce the 95% gate)"
        )
        return self

TASK 3 — Create packages/agents/lynch_pitch/tools.py:

async def get_financial_summary(coverage_id: str, db) -> dict:
    # Query kpi_timeseries for this coverage: get latest values of standard financial KPIs
    # Returns: {"revenue": NormalizedValue, "gross_margin": NormalizedValue, 
    #           "fcf": NormalizedValue, "net_debt": NormalizedValue, ...}
    # Used to pre-populate financial data before RAG search

async def get_management_credibility_score(coverage_id: str, db) -> dict | None:
    # Query research_outputs for prior quarterly_update outputs for this coverage
    # Extract management_credibility field from the latest one
    # Returns: {"score": "Strong"|"Mixed"|"Weak", "quarters_tracked": int} or None

async def save_bull_case(coverage_id: str, tenant_id: str, content: str, 
                          citations: list[dict], citation_coverage_pct: float,
                          llm_used: str, tokens_used: int, db) -> str:
    # INSERT into research_outputs with output_type="lynch_pitch"
    # Return output_id

TASK 4 — Create packages/agents/lynch_pitch/agent.py:

class LynchPitchAgent(BaseAgent):
    agent_type = AgentType.LYNCH_PITCH
    
    async def _execute(self, message: AgentMessage) -> AgentOutput:
        coverage_id = message.coverage_id
        tenant_id = message.tenant_id
        
        # Step 1: Retrieve relevant context from RAG (parallel searches for efficiency)
        queries = [
            "business model revenue how does the company make money",
            "gross margin operating margin profitability",
            "balance sheet debt cash free cash flow",
            "competitive advantage moat differentiation",
            "risks risk factors threats",
            "growth drivers expansion opportunities",
        ]
        
        # Run all RAG searches in parallel
        results = await asyncio.gather(*[
            self.retriever.retrieve(q, tenant_id, coverage_id, top_k=5, rerank_top_n=3)
            for q in queries
        ])
        
        # Step 2: Get financial summary and credibility score
        fin_summary = await get_financial_summary(coverage_id, self.db)
        cred_score = await get_management_credibility_score(coverage_id, self.db)
        
        # Step 3: Build context from retrieved chunks
        context = self._build_rag_context(results, queries)
        
        # Step 4: Get company name + ticker from coverage table
        company_info = await self._get_company_info(coverage_id, self.db)
        
        # Step 5: Build messages and call LLM
        retry_prompt = message.payload.get("retry_prompt")  # set by Citation Enforcer on retry
        
        messages = [
            {"role": "system", "content": LYNCH_PITCH_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_user_message(
                company_info, context, fin_summary, cred_score, retry_prompt
            )}
        ]
        
        content, model_used, tokens = await self._call_llm(
            messages=messages,
            tier=LLMTier.PRIMARY,
            max_tokens=6000,
        )
        
        # Step 6: Parse and validate
        pitch = self._parse_pitch_output(content, coverage_id, company_info, model_used)
        
        # Step 7: Save to research_outputs (Citation Enforcer will approve/reject after)
        output_id = await save_bull_case(
            coverage_id, tenant_id, content, pitch.all_citations,
            pitch.citation_coverage_pct, model_used, tokens, self.db
        )
        
        return AgentOutput(
            message_id=output_id,
            agent=AgentType.LYNCH_PITCH,
            task_id=message.task_id,
            coverage_id=coverage_id,
            tenant_id=tenant_id,
            content=content,
            citations=pitch.all_citations,
            citation_coverage_pct=pitch.citation_coverage_pct,
            llm_used=model_used,
            tokens_used=tokens,
            latency_ms=0,
        )
    
    def _build_rag_context(self, results: list[list], queries: list[str]) -> str:
        # Format retrieved chunks as evidence for the LLM
        # Group by query, deduplicate chunk_ids, format as:
        # EVIDENCE FOR "{query}":
        # [Doc Name, Section]: "relevant passage"
        # ...
        context_parts = []
        seen_chunk_ids = set()
        for query, chunks in zip(queries, results):
            context_parts.append(f"\nEVIDENCE FOR '{query}':")
            for chunk in chunks:
                if chunk.chunk_id not in seen_chunk_ids:
                    seen_chunk_ids.add(chunk.chunk_id)
                    doc_name = chunk.metadata.get("document_name", "Unknown")
                    section = chunk.metadata.get("section_name", "Unknown Section")
                    context_parts.append(f'[{doc_name}, {section}]: "{chunk.content[:500]}"')
        return "\n".join(context_parts)
    
    def _build_user_message(self, company_info: dict, context: str, 
                             fin_summary: dict, cred_score: dict | None,
                             retry_prompt: str | None) -> str:
        parts = [
            f"Company: {company_info['company_name']} ({company_info['ticker']})",
            f"\nPre-computed financial summary (verify against documents):\n{json.dumps(fin_summary, indent=2)}",
        ]
        if cred_score:
            parts.append(f"\nManagement credibility from prior quarters: {json.dumps(cred_score)}")
        parts.append(f"\nDocument evidence base:\n{context}")
        if retry_prompt:
            parts.append(f"\n\nPREVIOUS ATTEMPT FAILED VALIDATION. Fix these issues:\n{retry_prompt}")
        parts.append("\nNow answer all 8 questions using ONLY the evidence above.")
        return "\n".join(parts)
    
    def _parse_pitch_output(self, content: str, coverage_id: str, 
                             company_info: dict, llm_used: str) -> LynchPitch:
        # Extract Q1-Q8 sections using ### Q{n}: headers
        # For each section: extract citations, compute citation_coverage_pct
        # Detect company_type from Q5 answer
        # Build and validate LynchPitch
        ...
    
    async def _get_company_info(self, coverage_id: str, db) -> dict:
        from sqlalchemy import text
        result = await db.execute(
            text("SELECT ticker, company_name FROM coverages WHERE id = :id"),
            {"id": coverage_id}
        )
        row = result.fetchone()
        return {"ticker": row.ticker, "company_name": row.company_name}

TASK 5 — Write unit tests tests/unit/test_lynch_pitch_agent.py:
Mock the retriever to return synthetic chunks with known citations:

1. _build_rag_context with 6 query results → deduplicates chunks by chunk_id
2. _build_user_message includes company name, context, and financial summary
3. _build_user_message includes retry_prompt when provided
4. _parse_pitch_output on valid 8-question output → LynchPitch with all fields
5. _parse_pitch_output on output with <8 questions → ValidationError
6. _parse_pitch_output: company_type extracted from Q5 answer ("fast grower" → FAST_GROWER)
7. Full _execute flow with mocked LLM: saves to research_outputs, returns AgentOutput
8. RAG searches run in parallel (verify asyncio.gather called, not sequential await)

CONSTRAINTS:
- The 6 RAG searches must run concurrently with asyncio.gather — do not use sequential awaits
- The retry_prompt in message.payload is set by the Citation Enforcer retry loop — always check for it
- The agent must never include knowledge about the company beyond what's in the retrieved chunks
- save_bull_case must be called even if citation_coverage_pct < 0.95 — the Enforcer handles gating

ACCEPTANCE CRITERIA:
1. LynchPitch for a company with 3 indexed 10-Ks → all 8 questions answered, ≥90% citation coverage
2. LynchPitch for a company with only revenue data → Q1/Q2/Q3 answered, Q4 says "Not found"
3. Citation Enforcer validates the output and approves it (end-to-end test)
4. All 8 unit tests pass
5. e2e latency target: Lynch Pitch completes in <90 seconds for a company with 500+ indexed chunks
```

---

## PROMPT 2.6 — Munger Invert Agent, KPI Tracker & Earnings Monitor

```
You are implementing the final three research agents for the Stock Analyst AI platform.
The Lynch Pitch Agent, CitationEnforcer, and all shared infrastructure are complete.
Working directory: packages/agents/

CONTEXT:
Three agents remain:
- Munger Invert: adversarial bear case — INVALIDATES the thesis using same documents
- KPI Tracker: extracts and maintains time-series KPIs from every filing
- Earnings Monitor: compares prior guidance to actual results, quote-for-quote

TASK 1 — Create packages/agents/munger_invert/agent.py:
MungerInvertAgent is structurally identical to LynchPitchAgent with these differences:

System prompt key differences (use MUNGER_INVERT_SYSTEM_PROMPT):
- Goal is NOT to be balanced. Goal is to INVALIDATE the thesis.
- 8 adversarial questions (NOT the Lynch questions):
  Q1: What is the most likely way an investor loses money here?
  Q2: Where is the business structurally (not cyclically) weak?
  Q3: What assumptions must go right — and what evidence suggests they won't?
  Q4: What could PERMANENTLY impair earnings or cash flow?
  Q5: Is the balance sheet a hidden risk? (off-balance-sheet items, covenant triggers)
  Q6: Where could management destroy shareholder value? (cite past evidence)
  Q7: Why might investors be fooling themselves? (narrative vs data divergence)
  Q8: What specific evidence from the documents proves this bear case right?
- Style: Direct. Skeptical. Prosecutorial. No hedging language.

Additional RAG queries for adversarial research:
- "risk factors material risks litigation regulatory" (search specifically in risk_factors section)
- "footnotes contingent liabilities off-balance-sheet operating leases" (search footnotes section)
- "debt covenant credit facility revolving credit" (balance sheet risk)
- "goodwill impairment writedown restructuring" (value destruction signals)
- "guidance revision lowered outlook missed" (management credibility)

Additional tools beyond Lynch Pitch tools:
async def search_risk_factors(coverage_id: str, tenant_id: str, retriever) -> list[dict]:
    # HybridRetriever search filtered to section_name containing "risk"
    # filters={"must": [{"key": "section_name", "match": {"any": ["risk_factors", "risk factors"]}}]}

async def search_footnotes(coverage_id: str, tenant_id: str, retriever) -> list[dict]:
    # HybridRetriever search filtered to section_name containing "notes" or "footnotes"

async def compare_narrative_to_data(coverage_id: str, kpi_name: str, db) -> dict | None:
    # Query kpi_timeseries for {coverage_id, kpi_name} history (last 6 periods)
    # Query research_outputs for prior quarterly_update outputs (extract guidance statements)
    # Returns: {"management_claim": str, "actual_trend": list, "divergence_detected": bool}

Save output as: await save_research_output(coverage_id, tenant_id, "munger_invert", ..., db)

TASK 2 — Create packages/agents/kpi_tracker/agent.py:
KPI Tracker is a structured extraction agent (not a reasoning agent — use SECONDARY tier GPT-4o).

Create infra/kpi_definitions.yaml first:
industries:
  enterprise_software:
    kpis: [ARR, NRR, churn_rate, CAC, LTV, paying_customers, seats]
  saas:
    kpis: [ARR, MRR, NRR, churn_rate, gross_retention, CAC, LTV, DAU, MAU]
  retail:
    kpis: [same_store_sales, units_per_sqft, inventory_turns, gross_margin, average_ticket]
  regional_banking:
    kpis: [NIM, NPL_ratio, CET1_ratio, ROE, ROA, efficiency_ratio, deposits_growth]
  semiconductor:
    kpis: [revenue, gross_margin, backlog, book_to_bill, utilization_rate, inventory_turns]
  manufacturing:
    kpis: [revenue, gross_margin, backlog, book_to_bill, utilization_rate, capex_pct_revenue]
  default:
    kpis: [revenue, gross_profit, gross_margin_pct, ebitda, net_income, eps_diluted, 
           fcf, capex, net_debt, cash_equivalents, shares_outstanding]

KPITrackerAgent._execute():
1. Load KPI list for this coverage's industry from kpi_definitions.yaml
2. For each document in this coverage that hasn't been KPI-extracted yet:
   a. Build extraction prompt: "Extract these KPIs from the document. For each, provide the exact quote."
   b. Call SECONDARY LLM (GPT-4o) with structured output (JSON mode):
      [{"kpi_name": str, "raw_value": str, "period": str, "exact_quote": str, 
        "document_name": str, "section": str, "page_number": int}]
   c. For each extracted KPI: FinancialNormalizer.normalize_value(raw_value)
   d. upsert_kpi_timeseries() with normalized value + citation
3. Compute YoY changes for all KPIs that have ≥2 periods
4. Return summary of KPIs updated

async def upsert_kpi_timeseries(coverage_id: str, kpi_data: list[dict], db) -> int:
    # For each KPI data point:
    # Check if (coverage_id, kpi_name, period) already exists
    # If exists with DIFFERENT value: set is_restated=True, log both old and new
    # If exists with SAME value: skip (idempotent)
    # If new: INSERT
    # Returns count of rows upserted

async def compute_yoy_change(coverage_id: str, kpi_name: str, db) -> dict | None:
    # Get last 2 annual (period_type="annual") data points for this KPI
    # Return {"current_period": str, "prior_period": str, "yoy_change_pct": float} or None

TASK 3 — Create packages/agents/earnings_monitor/agent.py:
EarningsMonitorAgent processes a NEW earnings filing against PRIOR guidance.

System prompt key structure (EARNINGS_MONITOR_SYSTEM_PROMPT):
Three mandatory sections:
SECTION 1 — GUIDANCE VS REALITY:
For each major guidance item from the prior period:
  PRIOR GUIDANCE: [Doc, Section]: "exact quote"
  ACTUAL RESULT:  [Doc, Section]: "exact quote"
  VERDICT: Beat / Met / Missed by [X%]
  MANAGEMENT EXPLANATION: [Doc, Section]: "exact quote"
  CREDIBILITY CHECK: [Has this explanation been used before?]
End section with: Management Credibility Score: Strong / Mixed / Weak + one-sentence rationale.

SECTION 2 — KPI ANALYSIS (Year-over-Year):
For each key KPI (from industry KPI list):
  Current quarter: [value] [Doc, Section]: "quote"
  Same quarter prior year: [value] [Doc, Section]: "quote"
  YoY Change: [%]
  Signal: what this trend means economically

SECTION 3 — WHAT ACTUALLY CHANGED:
- Materially improved (with evidence)
- Materially deteriorated (with evidence)
- Genuinely new (strategy change, pricing, cost structure)
- Unchanged despite management emphasis (call out gaps)

FINAL SUMMARY (3 verdicts only):
Execution vs expectations: Improving / Stable / Deteriorating
Management credibility: Strong / Mixed / Weak
Business momentum vs last year: Better / Same / Worse

EarningsMonitorAgent._execute():
1. Get the latest NEW document (doc flagged in payload as "new_document_id")
2. Get prior quarter documents (all docs with filing_type in ["10-Q","10-K"] EXCEPT the new one)
3. Retrieve: prior guidance from older docs; current results from new doc
4. Build compare_management_language context (recurring excuse detection)
5. Call PRIMARY LLM with the 3-section structure
6. After approval: update_credibility_score(), trigger KPI Tracker for new document
7. Save as output_type="quarterly_update"

async def compare_management_language(coverage_id: str, current_doc_id: str,
                                       tenant_id: str, retriever) -> str:
    # Search historical docs for common management excuse phrases:
    # "supply chain", "macro environment", "temporary", "one-time", "headwind"
    # Return formatted list: phrase → how many times used → which quarters
    
async def update_credibility_score(coverage_id: str, quarter: str, 
                                    score: str, db) -> None:
    # Store credibility verdict in research_outputs metadata for this quarter
    # This accumulates across quarters for the management track record

TASK 4 — Add KPI dashboard API endpoint:
In apps/api/routers/coverages.py:
GET /api/v1/coverages/{id}/kpis:
  Returns all KPIs with time-series data for this coverage
  Group by kpi_name, sort periods chronologically
  Include YoY change % for each period pair
  Include citation for each data point

GET /api/v1/coverages/{id}/kpis/{kpi_name}:
  Returns single KPI full time-series with all citations

TASK 5 — Build KPI Dashboard UI page:
apps/web/app/(protected)/coverages/[id]/kpis/page.tsx:
- KPI selector tabs: group by "Financial" and "Operational" based on industry
- Time-series line chart per KPI (Recharts LineChart):
  - X axis: period labels
  - Y axis: normalized values
  - Two lines: quarterly (thinner) and annual (thicker)
  - Restatement indicator: render both old and new value as separate dots at the restated period, connected by dotted line
- Hover tooltip shows: value, period, and the exact citation quote
- YoY change badge: green up arrow (positive), red down arrow (negative)

TASK 6 — Write integration test tests/integration/test_kpi_tracker.py:
Prerequisites: AAPL coverage with 3 indexed 10-Ks.
1. Run KPITrackerAgent → revenue, gross_margin, net_income populated for 3 years
2. Each KPI row has citation field with document_name and exact_quote
3. compute_yoy_change for revenue → returns non-null with correct period labels
4. Upsert same value twice → idempotent (count stays the same)
5. Upsert different value for same period → is_restated=True on newer row

CONSTRAINTS:
- Munger Invert must still pass Citation Enforcer — adversarial tone does not excuse missing citations
- KPI Tracker uses SECONDARY (GPT-4o) not PRIMARY — it's structured extraction, not reasoning
- EarningsMonitor requires BOTH a new document AND prior documents — if only one exists, return PREREQUISITE_MISSING
- The KPI dashboard must handle null values gracefully (skip null points in Recharts, don't crash)
- upsert_kpi_timeseries must be idempotent — safe to run multiple times on the same document

ACCEPTANCE CRITERIA:
1. MungerInvertAgent on a company with risk factors in 10-K → cites risk_factors section in Q1-Q2
2. KPITrackerAgent on 4 quarters → 12+ KPI time-series rows in database
3. EarningsMonitorAgent with prior 10-Q + new 10-Q → guidance vs reality section populated
4. KPI dashboard renders charts for revenue and gross_margin with correct data
5. All integration tests in test_kpi_tracker.py pass
```
