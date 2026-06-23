# Stock Analyst AI — Agentic Framework Architecture
### Enterprise-Grade, On-Premise, Multi-Tenant | v1.0

**Deployment:** On-Premise (Self-Hosted)  
**Scale:** Institutional / SaaS — 10+ Analysts  
**LLM Layer:** Anthropic Claude (Primary) · OpenAI GPT-4o (Secondary) · Llama 3.1 70B (Local Fallback)  
**Prepared by:** AI Architect / SME Review  

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture Overview](#2-system-architecture-overview)
3. [Agentic Framework — Full Design](#3-agentic-framework--full-design)
4. [Agent Definitions — Prompts, Skills & Tools](#4-agent-definitions--prompts-skills--tools)
5. [Tech Stack — Full Specification](#5-tech-stack--full-specification)
6. [Data Models & API Design](#6-data-models--api-design)
7. [RAG Pipeline & Knowledge Architecture](#7-rag-pipeline--knowledge-architecture)
8. [Multi-Tenancy & Security](#8-multi-tenancy--security)
9. [Phased Development Plan](#9-phased-development-plan)
10. [On-Premise Deployment Architecture](#10-on-premise-deployment-architecture)
11. [Observability & Quality Assurance](#11-observability--quality-assurance)
12. [Directory & Project Structure](#12-directory--project-structure)

---

## 1. Executive Summary

This document specifies the complete architecture for an **Agentic Stock Research Platform** — a self-hosted, multi-analyst system that automates the 5-step equity research workflow defined in the source methodology:

| Methodology Step | System Equivalent |
|---|---|
| Step 1: Project Setup | Coverage Creation + Tenant Isolation |
| Step 2: Industry Fundamentals | Industry Analyst Agent |
| Step 3: Company History | Document Ingestion Agent + SEC EDGAR Connector |
| Step 4: Bull / Bear Cases | Lynch Pitch Agent + Munger Invert Agent |
| Step 5: Quarterly Update | Earnings Monitor Agent + KPI Tracker Agent |

The system enforces **quote-first, source-disciplined** outputs at the framework level — not as a user instruction but as a hard structural constraint in every agent's output schema and prompt chain. No agent may surface a factual claim without a traceable document citation.

---

## 2. System Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        ANALYST FRONTEND                             │
│          Next.js 14 · shadcn/ui · TailwindCSS · WebSockets         │
└───────────────────────────┬─────────────────────────────────────────┘
                            │ HTTPS / WSS
┌───────────────────────────▼─────────────────────────────────────────┐
│                      API GATEWAY LAYER                              │
│            FastAPI · JWT Auth · Rate Limiting · Keycloak            │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────────────┘
       │          │          │          │          │
┌──────▼───┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────────────────┐
│ Coverage │ │ Docs   │ │ Agent  │ │Reports │ │  Admin / Tenant    │
│   API    │ │  API   │ │  API   │ │  API   │ │      API           │
└──────┬───┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────────────────┘
       │         │          │          │           │
┌──────▼─────────▼──────────▼──────────▼───────────▼────────────────┐
│                    ORCHESTRATOR AGENT (LangGraph)                   │
│         Task Router · State Machine · Memory Manager               │
└────┬──────────┬──────────┬──────────┬──────────┬───────────────────┘
     │          │          │          │          │
┌────▼───┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────┐ ┌───▼────────────────┐
│Industry│ │Ingest  │ │Lynch   │ │Munger  │ │ Earnings Monitor   │
│Analyst │ │Agent   │ │Pitch   │ │Invert  │ │ + KPI Tracker      │
│ Agent  │ │        │ │ Agent  │ │ Agent  │ │    Agent           │
└────┬───┘ └───┬────┘ └───┬────┘ └───┬────┘ └───┬────────────────┘
     │         │          │          │           │
┌────▼─────────▼──────────▼──────────▼───────────▼────────────────┐
│                    SHARED SERVICES LAYER                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │  LLM Router  │  │  RAG Engine  │  │   Citation Enforcer   │  │
│  │  (LiteLLM)   │  │ (LlamaIndex) │  │   (Output Validator)  │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────────────┐  │
│  │  Tool Registry│  │  Memory Bus  │  │   Audit Logger        │  │
│  │  (MCP-style) │  │  (Redis)     │  │   (Structured)        │  │
│  └──────────────┘  └──────────────┘  └───────────────────────┘  │
└────┬──────────────────────┬───────────────────────┬──────────────┘
     │                      │                       │
┌────▼────┐          ┌──────▼──────┐        ┌──────▼──────┐
│ Qdrant  │          │ PostgreSQL  │        │   MinIO     │
│ Vector  │          │  Metadata   │        │  Document   │
│  Store  │          │  + RLS      │        │   Storage   │
└─────────┘          └─────────────┘        └─────────────┘
```

---

## 3. Agentic Framework — Full Design

### 3.1 Orchestration Pattern

The system uses a **Hierarchical Multi-Agent Architecture** with a **Plan-and-Execute + ReAct hybrid** pattern:

- **Planning Layer:** The Orchestrator decomposes user intent into a directed task graph
- **Execution Layer:** Specialist agents execute leaf tasks using tools and skills
- **Reflection Layer:** The Citation Enforcer validates all outputs before surfacing to user
- **Memory Layer:** Short-term (Redis), Long-term (Qdrant), Episodic (PostgreSQL)

### 3.2 Agent Hierarchy

```
Level 0 (Entry):    User Intent
Level 1 (Router):   Orchestrator Agent  ← routes, plans, monitors
Level 2 (Domain):   Industry Analyst · Document Ingestion · Research Writer
Level 3 (Task):     Lynch Pitch · Munger Invert · KPI Tracker · Guidance Auditor
Level 4 (Atomic):   SEC Fetcher · PDF Parser · Embedding Writer · Citation Checker
```

### 3.3 Agent Communication Protocol

All agents communicate via a **structured message envelope**:

```python
class AgentMessage(BaseModel):
    message_id: str              # UUID
    sender: AgentType
    recipient: AgentType
    task_id: str
    coverage_id: str             # which stock
    tenant_id: str               # which org
    payload: dict
    requires_citation: bool = True
    llm_preference: LLMTier     # PRIMARY / SECONDARY / LOCAL
    timestamp: datetime
    parent_message_id: str | None
```

### 3.4 State Machine (LangGraph)

Each coverage analysis runs as a **persistent LangGraph state graph**:

```
[START]
   │
   ▼
[coverage_init]  →  [industry_analysis]  →  [doc_ingestion]
                                                    │
                              ┌─────────────────────┤
                              ▼                     ▼
                     [lynch_pitch]          [munger_invert]
                              │                     │
                              └──────────┬──────────┘
                                         ▼
                                [citation_validation]
                                         │
                              ┌──────────┴──────────┐
                              ▼                     ▼
                         [APPROVED]           [REJECTED → retry]
                              │
                              ▼
                     [quarterly_monitor]  (persistent loop)
                              │
                          [END / STANDBY]
```

---

## 4. Agent Definitions — Prompts, Skills & Tools

---

### AGENT 1: Orchestrator Agent

**Role:** Master coordinator. Never generates research. Routes, plans, delegates, monitors.

**System Prompt:**
```
You are the Orchestrator for a professional equity research platform.
Your only job is to plan, route, and monitor — never to generate research yourself.

ROUTING RULES:
- Industry overview requests → IndustryAnalystAgent
- Document fetch/upload requests → DocumentIngestionAgent
- "Why own this stock" requests → LynchPitchAgent
- "How could I lose money" requests → MungerInvertAgent
- Earnings analysis requests → EarningsMonitorAgent
- KPI trend requests → KPITrackerAgent

PLANNING RULES:
1. Always check if a coverage (stock project) exists before routing.
2. Always check if industry fundamentals are loaded before allowing research.
3. Always check if minimum 3 years of filings are present before Bull/Bear cases.
4. If prerequisites are missing, return a PREREQUISITE_MISSING status with 
   exact instructions for what the user must supply.

OUTPUT FORMAT (always JSON):
{
  "plan_id": "<uuid>",
  "steps": [{"step": 1, "agent": "<name>", "skill": "<name>", "input": {}}],
  "estimated_duration_seconds": <int>,
  "prerequisites_met": <bool>,
  "missing_prerequisites": ["<description>"]
}
```

**Tools:**
- `check_coverage_exists(coverage_id)`
- `check_industry_loaded(coverage_id)`
- `check_filing_count(coverage_id, min_years)`
- `list_available_agents()`
- `dispatch_task(agent, skill, payload)`
- `get_task_status(task_id)`

**Skills:** `route`, `plan`, `prerequisite_check`, `task_monitor`

---

### AGENT 2: Industry Analyst Agent

**Role:** Produces the Step 2 industry primer. Uses web research and/or uploaded documents. Runs once per industry; output is saved and reused across all stocks in that industry.

**System Prompt:**
```
You are a senior industry analyst writing for long-term equity investors.
You produce factual, structured industry overviews — no opinions, no hype, no forecasts 
without mechanisms.

EVIDENCE DISCIPLINE:
- If using uploaded documents: cite [Document Name, Section]: "exact quote"
- If using web research: cite [Source Name, URL, Date]: "exact quote"  
- If a claim is inferred, mark it explicitly: (inferred from [source])
- If a claim cannot be sourced, mark it: (unknown — not found in available sources)
- NEVER state an unsourced claim as fact.

OUTPUT STRUCTURE (mandatory, 6 sections + synthesis):
1. Industry Purpose & Core Economics
2. Industry Structure & Competitive Shape
3. Demand & Growth Drivers
4. Supply Side, Cost Structure & Constraints
5. Technology, Regulation & Structural Change
6. Medium-Term Outlook (5–10 Years)

INVESTOR SYNTHESIS (5 bullets, each ≤ 2 sentences):
- Core economic engine
- Primary growth lever
- Structural constraint investors underestimate
- Key risk that could change trajectory
- What kind of companies tend to win

TARGET LENGTH: 1,200–1,800 words. Dense, no filler.
LLM SETTING: Use extended thinking. Prioritize Claude Opus.
```

**Tools:**
- `web_search(query, max_results)` — Tavily API
- `fetch_url(url)` — for regulator/industry body PDFs
- `rag_search(query, scope="industry", industry_id)` — search uploaded industry docs
- `save_industry_primer(industry_id, content, citations)`

**Skills:** `industry_overview`, `competitive_analysis`, `regulatory_scan`

**Output Schema:**
```python
class IndustryPrimer(BaseModel):
    industry_id: str
    industry_name: str
    sections: dict[str, str]        # section_name → content with inline citations
    investor_synthesis: list[str]   # 5 bullets
    all_citations: list[Citation]
    word_count: int
    llm_used: str
    created_at: datetime
    confidence_score: float         # 0-1, based on citation coverage
```

---

### AGENT 3: Document Ingestion Agent

**Role:** Fetches, validates, parses, chunks, embeds, and indexes all company documents. Enforces the quote-first rule by making every chunk retrievable by exact text.

**System Prompt:**
```
You are a document ingestion specialist for an equity research system.
Your job is to process financial documents with zero data loss and full traceability.

INGESTION RULES:
1. Every chunk must carry: document_name, filing_type, period, page_number, section_name
2. Tables must be extracted as structured data (not flattened text)
3. Financial figures must be normalized: currency, unit (millions/billions), period
4. Duplicate detection: reject documents already indexed (hash check)
5. Quality check: flag documents with <50% text extraction rate (likely scanned)

SUPPORTED DOCUMENT TYPES:
- SEC 10-K (Annual Report)
- SEC 10-Q (Quarterly Report)  
- SEC 8-K (Material Events)
- Earnings Call Transcripts
- Investor Day Presentations
- Annual Reports (non-US)
- Analyst Research Notes (uploaded by user)
- Custom Notes (uploaded by user)

OUTPUT: Structured ingestion report with chunk count, table count, figure count, 
        any extraction warnings, and a document quality score.
```

**Tools:**
- `fetch_sec_filing(ticker, form_type, year)` — SEC EDGAR API
- `fetch_ir_page(ticker)` — IR page scraper
- `parse_pdf(file_path)` — PyMuPDF + Unstructured.io
- `extract_tables(file_path)` — Docling
- `normalize_financials(raw_table)` — unit/currency normalization
- `chunk_document(content, strategy)` — semantic chunking
- `embed_chunks(chunks)` — local embedding model
- `store_in_vector_db(chunks, metadata)` — Qdrant
- `store_in_object_store(file, metadata)` — MinIO
- `register_document(coverage_id, document_metadata)` — PostgreSQL

**Skills:** `sec_fetch`, `pdf_parse`, `table_extract`, `embed_index`, `doc_validate`

---

### AGENT 4: Lynch Pitch Agent (Bull Case)

**Role:** Produces the Step 4A Lynch Pitch — a simple, source-disciplined investment case answering "why would I own this stock?"

**System Prompt:**
```
You are a long-term equity analyst writing in the style of Peter Lynch.
You produce SHORT, PLAIN, SOURCE-DISCIPLINED investment pitches.

ABSOLUTE RULES:
1. USE ONLY documents in this coverage's knowledge base. No external knowledge.
2. For EVERY factual claim or metric: provide the exact quote first, then interpretation.
   Format: [Document Name, Page/Section]: "exact quote" → your interpretation
3. If you cannot find a quote supporting a claim: DO NOT MAKE THE CLAIM.
   Write instead: "Not found in uploaded documents."
4. No buzzwords. No macro speculation. No DCF or valuation models.
5. Plain English. Short sentences. A smart teenager should understand this.

ANSWER THESE 8 QUESTIONS IN ORDER:
1. In one sentence, what does this company do?
2. What is the single reason this stock could work? ONE idea only.
3. How does the company actually make money? (Revenue model, margins)
4. Balance sheet health: debt, cash, free cash flow. State the period.
5. What type of company is this? 
   [slow grower / stalwart / fast grower / cyclical / turnaround / asset play]
6. What could go wrong? (Be honest — this makes the pitch credible)
7. Why might the market be mispricing this?
8. Bottom line: 3–4 sentences covering why it's interesting, what must go right, 
   and what would make you wrong.

WRITING STYLE: Direct. Honest. No hype. No "exciting opportunity" language.
```

**Tools:**
- `rag_search(query, scope="coverage", coverage_id)` — retrieve relevant chunks
- `get_financial_summary(coverage_id, period)` — pre-computed financials
- `get_management_credibility_score(coverage_id)` — from prior quarters
- `validate_citations(content)` — Citation Enforcer
- `save_bull_case(coverage_id, content)`

**Skills:** `lynch_pitch`, `balance_sheet_read`, `business_model_parse`, `risk_identification`

**Output Schema:**
```python
class LynchPitch(BaseModel):
    coverage_id: str
    company_name: str
    answers: dict[int, AnswerWithCitation]  # Q1-Q8 each with citations
    company_type: CompanyType
    all_citations: list[Citation]
    citation_coverage_pct: float    # % of claims that have citations
    word_count: int
    generated_at: datetime
    llm_used: str
    # Fails validation if citation_coverage_pct < 0.95
```

---

### AGENT 5: Munger Invert Agent (Bear Case)

**Role:** Produces the Step 4B Munger Invert — adversarial analysis designed to INVALIDATE the investment thesis.

**System Prompt:**
```
You are a skeptical, adversarial equity analyst applying Charlie Munger's inversion 
principle: assume the investment is BAD and work backwards to prove it.

Your goal is NOT to be balanced. Your goal is to INVALIDATE the thesis as forcefully 
as the documents allow.

ABSOLUTE RULES (same as Lynch Pitch):
1. USE ONLY documents in this coverage's knowledge base.
2. Every factual claim requires an exact prior quote with source.
3. Format: [Document Name, Page/Section]: "exact quote" → adversarial interpretation
4. If you cannot find a quote: DO NOT MAKE THE CLAIM.
5. No macro speculation. Ground every risk in evidence from the filings.

ANSWER THESE 8 QUESTIONS IN ORDER:
1. What is the most likely way an investor could lose money here?
2. Where is the business structurally weak? (Not cyclically — structurally)
3. What assumptions need to go right — and what evidence suggests they might not?
4. What could permanently impair earnings or cash flow? (Not temporarily)
5. Is the balance sheet a hidden risk? (Off-balance-sheet items, covenant triggers)
6. Where could management destroy shareholder value? (Past evidence preferred)
7. Why might investors be fooling themselves? (Narrative vs data divergence)
8. What specific evidence from the documents would prove this bear case right?

WRITING STYLE: Direct. Skeptical. Prosecutorial. Every weakness stated plainly.
No hedging language ("could potentially maybe..."). State risks as the most 
plausible interpretation of the evidence.
```

**Tools:** Same as Lynch Pitch Agent, plus:
- `search_risk_factors(coverage_id)` — targeted 10-K risk factor retrieval
- `search_footnotes(coverage_id)` — off-balance-sheet, contingent liabilities
- `compare_narrative_to_data(coverage_id)` — management language vs financial trends

**Skills:** `munger_invert`, `risk_deep_dive`, `management_track_record`, `footnote_analysis`

---

### AGENT 6: Earnings Monitor Agent

**Role:** Executes the Step 5 quarterly update — comparing new earnings to prior guidance, historical KPIs, and the thesis.

**System Prompt:**
```
You are a long-term equity analyst processing a fresh earnings report.
You have full access to this company's historical filings and prior guidance.
Your job: compare what management SAID they would do vs what they ACTUALLY DID.

ABSOLUTE RULES:
1. Every claim requires dual citation: prior document quote + new document quote.
2. Format for guidance tracking:
   PRIOR GUIDANCE: [Doc, Section]: "exact quote"
   ACTUAL RESULT:  [Doc, Section]: "exact quote"  
   VERDICT: Beat / Met / Missed by [X%]
   MANAGEMENT EXPLANATION: [Doc, Section]: "exact quote"
   CREDIBILITY CHECK: [Has this explanation been used before? When?]

SECTION 1 — GUIDANCE VS REALITY
For each major guidance item from prior period:
- What was promised (exact quote + source)
- What was delivered (exact quote + source)
- Variance (quantified)
- Management's explanation (exact quote)
- Whether explanation is data-backed or vague
End with: Management Credibility Score this quarter [Strong / Mixed / Weak] + rationale.

SECTION 2 — KPI ANALYSIS (Year-over-Year)
For each key KPI specific to this industry:
- Current quarter value + source quote
- Same quarter prior year + source quote
- % change
- Economic signal (what does this trend mean for the business?)
- Alignment with management narrative (supports / contradicts / neutral)

SECTION 3 — WHAT ACTUALLY CHANGED?
- Materially improved (with evidence)
- Materially deteriorated (with evidence)
- Genuinely new (strategy, pricing, cost structure, capital allocation)
- Unchanged despite management emphasis (call out the gap)

FINAL SUMMARY (3 verdicts only):
- Execution vs expectations: Improving / Stable / Deteriorating
- Management credibility: Strong / Mixed / Weak
- Business momentum vs last year: Better / Same / Worse
```

**Tools:**
- `get_prior_guidance(coverage_id, period)` — retrieve prior quarter guidance chunks
- `get_kpi_history(coverage_id, kpi_name, periods)` — time-series KPI data
- `rag_search(query, scope="coverage", doc_filter="latest")` — search new filing
- `compare_management_language(coverage_id, current_period)` — recurring excuses detector
- `update_credibility_score(coverage_id, quarter, score)` — update history
- `update_kpi_history(coverage_id, kpis)` — persist new KPI data

**Skills:** `earnings_analysis`, `guidance_audit`, `kpi_tracking`, `management_credibility`

---

### AGENT 7: KPI Tracker Agent

**Role:** Maintains a structured, longitudinal KPI database for every coverage. Automatically identifies the relevant KPIs per industry, extracts values from every filing, and computes trends.

**System Prompt:**
```
You are a financial data extraction specialist.
Your job: identify, extract, and maintain KPI time-series for equity coverage.

EXTRACTION RULES:
1. Always cite: [Document, Page/Table]: "exact figure as written"
2. Then normalize: standardized unit, period, currency
3. Flag restatements: if a prior-period figure differs from what was filed, log both
4. Flag definition changes: if management changes how they define a KPI, log the change

STANDARD KPIs (extracted for every coverage):
Financial: Revenue, Gross Profit, Gross Margin %, EBITDA, EBIT, Net Income,
           EPS (diluted), FCF, CapEx, Net Debt, Cash & Equivalents,
           Shares Outstanding, Dividends per Share

Operational (industry-specific — auto-detected from industry primer):
- SaaS: ARR, NRR, Churn Rate, CAC, LTV, Seats/Users
- Retail: Same-Store Sales, Units/Sq ft, Inventory Turns
- Banks: NIM, NPL Ratio, CET1 Ratio, ROE, ROA
- Manufacturing: Utilization Rate, Backlog, Book-to-Bill
- etc.

OUTPUT: Structured time-series JSON, normalized, with citation trail for every data point.
```

**Tools:**
- `detect_industry_kpis(industry_id)` — map industry to KPI set
- `extract_kpis_from_doc(document_id, kpi_list)` — structured extraction
- `normalize_kpi(raw_value, unit, period)` — normalization
- `upsert_kpi_timeseries(coverage_id, kpi_data)` — PostgreSQL time-series table
- `compute_yoy_change(coverage_id, kpi_name)` — YoY delta computation
- `detect_restatement(coverage_id, kpi_name, period)` — restatement flagging

---

### SHARED SERVICE: Citation Enforcer

**Role:** Not a research agent — a validation gate. Every agent output must pass through Citation Enforcer before being stored or surfaced to users.

**Validation Rules:**
```python
class CitationEnforcer:
    def validate(self, output: AgentOutput) -> ValidationResult:
        checks = [
            self.check_citation_coverage(output),     # >= 95% claims cited
            self.check_quote_format(output),          # [Doc, Section]: "quote"
            self.check_quote_exists_in_rag(output),   # quote retrievable from DB
            self.check_no_unsourced_numbers(output),  # all figures have citations
            self.check_no_future_speculation(output), # no "will", "expects to"
            self.check_inference_labeling(output),    # inferences labeled
        ]
        if all(c.passed for c in checks):
            return ValidationResult(approved=True)
        else:
            return ValidationResult(
                approved=False,
                failed_checks=checks,
                retry_prompt=self.build_retry_prompt(checks)  # send back to agent
            )
```

**Retry Logic:** Up to 3 retries. If still failing after 3: surface to user with a "PARTIAL — manual review required" flag.

---

## 5. Tech Stack — Full Specification

### 5.1 LLM Layer

| Component | Technology | Rationale |
|---|---|---|
| Primary LLM | **Anthropic Claude Opus 4.6** | 200K context window for full filings; best-in-class long-doc analysis; Extended Thinking for industry research |
| Secondary LLM | **OpenAI GPT-4o** | Structured JSON extraction, table parsing; fast, reliable for KPI tasks |
| Local Fallback | **Llama 3.1 70B via Ollama** | Air-gapped operation, sensitive filings, cost containment |
| LLM Gateway | **LiteLLM** | Unified OpenAI-compatible API across all three providers; automatic failover, cost tracking, rate limiting |
| Embedding Model | **nomic-embed-text-v1.5 (local)** | 8192 token context; runs on-premise; no data leaves the org |

### 5.2 Agentic Orchestration

| Component | Technology | Rationale |
|---|---|---|
| Agent Framework | **LangGraph** | Native support for stateful multi-agent graphs; persistence; human-in-the-loop; built-in retry logic |
| Agent Memory | **LangGraph Checkpointer + PostgreSQL** | Durable state across sessions; time-travel debugging |
| Tool Protocol | **MCP (Model Context Protocol)** | Standard tool interface; pluggable connectors; future-proof |
| Background Tasks | **Celery + Redis** | Async document ingestion; scheduled quarterly monitoring |
| Task Scheduler | **Celery Beat** | Earnings calendar integration; auto-trigger quarterly updates |

### 5.3 RAG & Knowledge Layer

| Component | Technology | Rationale |
|---|---|---|
| Vector Database | **Qdrant** | Self-hosted; best performance for filtered search (critical for tenant isolation); native sparse+dense hybrid search |
| RAG Framework | **LlamaIndex** | Best-in-class for financial document RAG; table-aware retrieval; citation metadata preservation |
| Chunking Strategy | **Semantic + Hierarchical** | Preserves section context; parent-child chunks for citation accuracy |
| Retrieval Strategy | **Hybrid (BM25 + Dense)** | Sparse for exact quote match; dense for semantic; critical for quote-first discipline |
| Reranker | **CrossEncoder (local)** | Reranks top-K results before sending to LLM; improves citation precision |

### 5.4 Document Processing

| Component | Technology | Rationale |
|---|---|---|
| PDF Parser | **PyMuPDF** | Fast, accurate text extraction; page-level metadata |
| Complex Documents | **Unstructured.io (self-hosted)** | Handles scanned PDFs, complex layouts, earnings slides |
| Table Extraction | **Docling (IBM)** | State-of-art table detection; outputs structured JSON |
| SEC Filing Fetch | **SEC EDGAR Full-Text Search API** | Official source; no third-party dependency |
| Financial Normalization | **Custom + pandas** | Unit normalization (M/B/T), currency, period standardization |

### 5.5 Data Storage

| Component | Technology | Rationale |
|---|---|---|
| Primary Database | **PostgreSQL 16** | Row-Level Security for tenant isolation; JSONB for flexible schemas; time-series via partitioned tables |
| Object Storage | **MinIO** | S3-compatible; fully self-hosted; stores raw PDFs, processed chunks |
| Cache / Message Bus | **Redis 7** | Agent short-term memory; Celery broker; pub/sub for real-time updates |
| Search | **Qdrant** | Doubles as vector + metadata filter store |

### 5.6 Backend

| Component | Technology | Rationale |
|---|---|---|
| API Framework | **FastAPI** | Async-native; automatic OpenAPI docs; Pydantic validation |
| Auth | **Keycloak** | Self-hosted; OIDC/OAuth2; RBAC; LDAP integration |
| Background Jobs | **Celery + Flower** | Distributed task execution; monitoring dashboard |
| WebSockets | **FastAPI WebSockets** | Real-time streaming of agent outputs to frontend |
| Data Validation | **Pydantic v2** | Output schema enforcement across all agents |

### 5.7 Frontend

| Component | Technology | Rationale |
|---|---|---|
| Framework | **Next.js 14 (App Router)** | Server components; streaming; SSR for report rendering |
| UI Components | **shadcn/ui** | Accessible, customizable; works with Tailwind |
| Styling | **TailwindCSS** | Rapid development; consistent design tokens |
| State Management | **Zustand** | Lightweight; no boilerplate |
| Data Fetching | **TanStack Query** | Caching, background refetch, optimistic updates |
| Charts | **Recharts + Tremor** | KPI time-series visualization; financial charts |
| Rich Text | **Tiptap** | Analyst notes editor with citation linking |

### 5.8 Observability

| Component | Technology | Rationale |
|---|---|---|
| LLM Tracing | **LangSmith** | Full trace of every agent call; token counting; latency; citation success rate |
| System Metrics | **Prometheus + Grafana** | Infrastructure and application metrics |
| Logging | **structlog + Loki** | Structured JSON logs; queryable via Grafana |
| Error Tracking | **Sentry (self-hosted)** | Frontend and backend error capture |
| Uptime | **Uptime Kuma** | Lightweight self-hosted uptime monitoring |

### 5.9 Infrastructure

| Component | Technology | Rationale |
|---|---|---|
| Container Runtime | **Docker** | Development and CI |
| Orchestration | **k3s (lightweight Kubernetes)** | On-premise k8s; lower overhead than full k8s |
| Service Mesh | **Traefik** | Reverse proxy; TLS termination; routing |
| CI/CD | **Gitea + Gitea Actions** | Fully self-hosted; no GitHub dependency |
| Secrets | **HashiCorp Vault** | Self-hosted secrets management; LLM API keys |
| Backup | **Velero + restic** | Kubernetes backup; volume snapshots |

---

## 6. Data Models & API Design

### 6.1 Core Data Models

```python
# ── Tenant / Organization ──────────────────────────────────────────
class Tenant(BaseModel):
    tenant_id: UUID
    name: str
    plan: Literal["starter", "professional", "enterprise"]
    created_at: datetime
    settings: TenantSettings

# ── User ───────────────────────────────────────────────────────────
class User(BaseModel):
    user_id: UUID
    tenant_id: UUID
    email: str
    role: Literal["viewer", "analyst", "senior_analyst", "admin"]
    created_at: datetime

# ── Coverage (= Stock Project) ─────────────────────────────────────
class Coverage(BaseModel):
    coverage_id: UUID
    tenant_id: UUID
    ticker: str
    company_name: str
    exchange: str
    industry_id: UUID
    created_by: UUID
    created_at: datetime
    status: Literal["setup", "active", "archived"]
    document_count: int
    last_updated: datetime

# ── Document ───────────────────────────────────────────────────────
class Document(BaseModel):
    document_id: UUID
    coverage_id: UUID
    tenant_id: UUID
    file_name: str
    filing_type: str          # "10-K", "10-Q", "transcript", "custom"
    period: str               # "FY2024", "Q3 2024"
    source: str               # "SEC EDGAR", "user_upload", "IR page"
    source_url: str | None
    storage_path: str         # MinIO path
    page_count: int
    chunk_count: int
    ingested_at: datetime
    quality_score: float      # 0-1

# ── Citation ───────────────────────────────────────────────────────
class Citation(BaseModel):
    citation_id: UUID
    document_id: UUID
    document_name: str
    filing_type: str
    period: str
    page_number: int
    section_name: str
    exact_quote: str
    chunk_id: str             # Qdrant point ID
    retrieved_at: datetime

# ── Research Output ────────────────────────────────────────────────
class ResearchOutput(BaseModel):
    output_id: UUID
    coverage_id: UUID
    output_type: Literal[
        "industry_primer", "lynch_pitch", "munger_invert", 
        "quarterly_update", "kpi_snapshot"
    ]
    content: str              # Markdown with inline citations
    citations: list[Citation]
    citation_coverage_pct: float
    approved_by_enforcer: bool
    llm_used: str
    tokens_used: int
    generated_at: datetime
    version: int

# ── KPI Time Series ────────────────────────────────────────────────
class KPIDataPoint(BaseModel):
    coverage_id: UUID
    kpi_name: str
    period: str
    period_type: Literal["annual", "quarterly"]
    value: float
    unit: str                 # "USD_millions", "percentage", "count"
    citation: Citation
    is_restated: bool
    restatement_note: str | None
```

### 6.2 REST API Endpoints

```
# Coverage Management
POST   /api/v1/coverages                    # Create new coverage
GET    /api/v1/coverages                    # List coverages (tenant-scoped)
GET    /api/v1/coverages/{id}               # Get coverage detail
DELETE /api/v1/coverages/{id}               # Archive coverage

# Document Management  
POST   /api/v1/coverages/{id}/documents     # Upload document
GET    /api/v1/coverages/{id}/documents     # List documents
DELETE /api/v1/coverages/{id}/documents/{doc_id}

# Agent Tasks
POST   /api/v1/coverages/{id}/tasks/industry-analysis
POST   /api/v1/coverages/{id}/tasks/fetch-filings
POST   /api/v1/coverages/{id}/tasks/lynch-pitch
POST   /api/v1/coverages/{id}/tasks/munger-invert
POST   /api/v1/coverages/{id}/tasks/quarterly-update
GET    /api/v1/tasks/{task_id}              # Task status
DELETE /api/v1/tasks/{task_id}              # Cancel task

# Research Outputs
GET    /api/v1/coverages/{id}/outputs       # List all outputs
GET    /api/v1/coverages/{id}/outputs/{output_id}
POST   /api/v1/coverages/{id}/outputs/{output_id}/approve  # Manual approval

# KPI Data
GET    /api/v1/coverages/{id}/kpis          # All KPIs with history
GET    /api/v1/coverages/{id}/kpis/{name}   # Single KPI time-series

# Search
POST   /api/v1/coverages/{id}/search        # RAG search within coverage
POST   /api/v1/search                       # Cross-coverage search (tenant-scoped)

# Admin
GET    /api/v1/admin/tenants
GET    /api/v1/admin/usage                  # Token usage, LLM costs
GET    /api/v1/admin/agents/health          # Agent health status
```

---

## 7. RAG Pipeline & Knowledge Architecture

### 7.1 Ingestion Pipeline (Step-by-Step)

```
[Document Upload / SEC Fetch]
         │
         ▼
[1. Hash Check] ──── duplicate? ──→ SKIP
         │
         ▼
[2. Format Detection]
   PDF / HTML / DOCX / TXT
         │
         ▼
[3. Text Extraction]
   PyMuPDF (text PDFs)
   Unstructured.io (scanned / complex)
   Docling (tables + charts)
         │
         ▼
[4. Quality Gate]
   Text coverage < 50%? → FLAG for manual review
         │
         ▼
[5. Structural Parsing]
   Identify: Title, Sections, Subsections, Tables, Footnotes
   Map to filing schema: {cover, mda, financials, notes, risk_factors}
         │
         ▼
[6. Hierarchical Chunking]
   Parent chunks: full sections (~2000 tokens)
   Child chunks:  paragraphs (~200 tokens)
   Table chunks:  each table as JSON + markdown
         │
         ▼
[7. Metadata Enrichment]
   Every chunk gets:
   {document_id, document_name, filing_type, period, page_number,
    section_name, parent_chunk_id, tenant_id, coverage_id}
         │
         ▼
[8. Embedding]
   nomic-embed-text-v1.5 (local, 768-dim)
         │
         ▼
[9. Dual Indexing]
   Qdrant: vector points with full metadata payload
   BM25 index: sparse keyword index (for exact quote retrieval)
         │
         ▼
[10. Registration]
    PostgreSQL: document record + chunk count + quality score
    MinIO: raw file stored at /tenants/{tid}/coverages/{cid}/docs/
```

### 7.2 Retrieval Strategy

```python
class HybridRetriever:
    """
    Two-stage retrieval designed for financial documents.
    Stage 1: Candidate retrieval (dense + sparse fusion)
    Stage 2: Reranking for citation precision
    """
    
    def retrieve(
        self, 
        query: str,
        coverage_id: str,
        tenant_id: str,
        top_k: int = 20,
        filters: dict | None = None
    ) -> list[ChunkWithCitation]:
        
        # Stage 1A: Dense retrieval (semantic similarity)
        dense_results = self.qdrant.search(
            query_vector=self.embed(query),
            filter={"coverage_id": coverage_id, "tenant_id": tenant_id, **filters},
            limit=top_k
        )
        
        # Stage 1B: Sparse retrieval (exact term / quote match)
        sparse_results = self.bm25.search(
            query=query,
            filter={"coverage_id": coverage_id},
            limit=top_k
        )
        
        # Stage 1C: RRF Fusion
        candidates = reciprocal_rank_fusion(dense_results, sparse_results)
        
        # Stage 2: CrossEncoder reranking
        reranked = self.reranker.rerank(query, candidates, top_n=8)
        
        # Stage 3: Parent chunk hydration (get full section context)
        hydrated = self.hydrate_parents(reranked)
        
        return hydrated
```

---

## 8. Multi-Tenancy & Security

### 8.1 Tenant Isolation Model

All data isolation is enforced at **three layers** — application, database, and vector store:

**PostgreSQL Row-Level Security:**
```sql
-- Applied to every table containing tenant data
ALTER TABLE coverages ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation ON coverages
    USING (tenant_id = current_setting('app.current_tenant_id')::uuid);
    
-- Applied via FastAPI middleware on every request:
-- SET LOCAL app.current_tenant_id = '{tenant_id}';
```

**Qdrant Collection Strategy:**
- Each tenant gets its own **Qdrant collection** (`tenant_{tenant_id}`)
- Coverage filter applied on every query via payload filter
- No cross-tenant collection access possible at API level

**MinIO Bucket Strategy:**
- One bucket per tenant: `stocks-{tenant_id}`
- Pre-signed URLs with short TTL for document access
- No public access; service account per tenant

### 8.2 RBAC Matrix

| Action | Viewer | Analyst | Senior Analyst | Admin |
|---|---|---|---|---|
| View research outputs | ✓ | ✓ | ✓ | ✓ |
| Run agent tasks | ✗ | ✓ | ✓ | ✓ |
| Upload documents | ✗ | ✓ | ✓ | ✓ |
| Approve/reject outputs | ✗ | ✗ | ✓ | ✓ |
| Create/archive coverages | ✗ | ✓ | ✓ | ✓ |
| Manage users | ✗ | ✗ | ✗ | ✓ |
| View LLM costs | ✗ | ✗ | ✓ | ✓ |
| Configure LLM routing | ✗ | ✗ | ✗ | ✓ |

### 8.3 Data Security

- All data at rest: AES-256 encryption (MinIO, PostgreSQL tablespace)
- All data in transit: TLS 1.3
- LLM API keys: HashiCorp Vault, rotated quarterly
- No PII sent to external LLMs without explicit opt-in
- Audit log: every agent call, every document access, every output — immutable, PostgreSQL append-only table
- Local fallback mode: Llama 3.1 for air-gapped operation when compliance requires zero external calls

---

## 9. Phased Development Plan

### Phase 0 — Foundation (Weeks 1–3)

**Goal:** Core infrastructure running locally. No agents yet.

- [ ] Repository setup (monorepo: `apps/api`, `apps/web`, `packages/agents`, `packages/rag`)
- [ ] Docker Compose: PostgreSQL, Redis, Qdrant, MinIO, Keycloak, Ollama
- [ ] Database schema + migrations (Alembic)
- [ ] FastAPI skeleton: auth middleware, tenant middleware, health endpoints
- [ ] Keycloak realm setup: roles, clients, test users
- [ ] MinIO bucket policy setup
- [ ] LiteLLM gateway: Claude + GPT-4o + Ollama routing config
- [ ] Basic Next.js shell: auth flow (Keycloak SSO), protected routes
- [ ] LangSmith workspace setup for tracing
- [ ] CI pipeline: Gitea Actions, lint, type-check, test

**Deliverable:** Authenticated multi-tenant shell. No AI yet. All infrastructure healthy.

---

### Phase 1 — Document Backbone (Weeks 4–7)

**Goal:** Full document ingestion pipeline working end-to-end.

- [ ] Document Ingestion Agent — core implementation
- [ ] SEC EDGAR API connector (Form 10-K, 10-Q, 8-K)
- [ ] PDF processing pipeline: PyMuPDF + Unstructured.io
- [ ] Table extraction: Docling integration
- [ ] Hierarchical chunking strategy
- [ ] Qdrant collection setup + metadata schema
- [ ] Embedding pipeline: nomic-embed-text-v1.5 (local Ollama)
- [ ] BM25 sparse index setup
- [ ] MinIO document storage + pre-signed URL service
- [ ] Ingestion API endpoints + Celery async tasks
- [ ] Document management UI: upload, status, list, delete
- [ ] Quality scoring + warning system
- [ ] Integration tests: ingest a real 10-K, verify chunks, verify retrieval

**Deliverable:** Upload any SEC filing → chunked, embedded, indexed, retrievable in <2 min.

---

### Phase 2 — Core Agents (Weeks 8–13)

**Goal:** All five primary agents working with Citation Enforcer.

**Week 8–9: Orchestrator + Citation Enforcer**
- [ ] LangGraph state graph: coverage workflow
- [ ] Orchestrator Agent: routing logic, prerequisite checks
- [ ] Citation Enforcer: validation rules, retry mechanism
- [ ] Agent message envelope + communication protocol

**Week 10: Industry Analyst Agent**
- [ ] System prompt implementation
- [ ] Tavily web search tool integration
- [ ] Industry primer output schema + storage
- [ ] Industry primer UI: rendered markdown with citation tooltips

**Week 11: Lynch Pitch + Munger Invert Agents**
- [ ] Lynch Pitch Agent: 8-question structure, RAG tools, output schema
- [ ] Munger Invert Agent: adversarial prompt, footnote search tool
- [ ] Side-by-side bull/bear UI view
- [ ] Citation hover: click any citation → original document opens at that page

**Week 12–13: Earnings Monitor + KPI Tracker Agents**
- [ ] KPI detection by industry type
- [ ] KPI extraction tool: structured output from filings
- [ ] KPI time-series storage (PostgreSQL partitioned table)
- [ ] Earnings Monitor Agent: 3-section structure
- [ ] Management credibility score accumulation
- [ ] Guidance vs Reality tracker (prior promise → actual result)
- [ ] KPI dashboard: time-series charts per metric

**Deliverable:** Full 5-step workflow automated for any stock with sufficient filings.

---

### Phase 3 — Quality, UX & Intelligence (Weeks 14–17)

**Goal:** Production-ready quality + analyst-grade UX.

- [ ] Citation accuracy evaluation: automated test suite against known filings
- [ ] Hallucination detection: cross-check cited quotes against source chunks
- [ ] LangSmith evaluation sets: per-agent quality scoring
- [ ] Streaming responses: WebSocket streaming of agent output to frontend
- [ ] Coverage dashboard: multi-stock portfolio overview
- [ ] Analyst notes editor: Tiptap with citation linking
- [ ] Export: PDF report generation (coverage summary + quarterly update)
- [ ] Earnings calendar: auto-trigger quarterly update when new filings appear
- [ ] Email/Slack notification: "New earnings processed for [TICKER]"
- [ ] LLM cost dashboard (per tenant, per coverage, per agent)
- [ ] Performance tuning: retrieval latency < 500ms, full output < 90s

**Deliverable:** System usable by real analysts with no engineering support.

---

### Phase 4 — Production Hardening (Weeks 18–20)

**Goal:** On-premise k3s deployment. Security audit. Load testing.

- [ ] k3s cluster setup: control plane + worker nodes
- [ ] Helm charts for all services
- [ ] Persistent volume setup (NFS or local-path)
- [ ] Traefik ingress: TLS, routing
- [ ] HashiCorp Vault: secret injection via CSI driver
- [ ] Velero backup: daily snapshots of PostgreSQL + MinIO
- [ ] Load testing: 10 concurrent analysts, stress test ingestion pipeline
- [ ] Security audit: OWASP top 10, tenant isolation penetration test
- [ ] Disaster recovery runbook
- [ ] Operator documentation: installation guide, upgrade guide

**Deliverable:** Production k3s cluster. Security-audited. Backup-tested. Documented.

---

## 10. On-Premise Deployment Architecture

### 10.1 k3s Node Layout

```
┌─────────────────────────────────────────────────────┐
│                   k3s CLUSTER                       │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │  Control Plane Node (8 CPU / 32GB RAM)      │    │
│  │  k3s server · etcd · Traefik · CoreDNS      │    │
│  └─────────────────────────────────────────────┘    │
│                                                     │
│  ┌───────────────────┐  ┌───────────────────────┐   │
│  │  App Worker Node  │  │  ML / GPU Worker Node │   │
│  │  (16 CPU/64GB)    │  │  (16 CPU/64GB/GPU)    │   │
│  │                   │  │                       │   │
│  │  FastAPI          │  │  Ollama (Llama 3.1)   │   │
│  │  Next.js          │  │  Embedding Model      │   │
│  │  Celery Workers   │  │  Unstructured.io      │   │
│  │  Keycloak         │  │  Reranker Model       │   │
│  └───────────────────┘  └───────────────────────┘   │
│                                                     │
│  ┌─────────────────────────────────────────────┐    │
│  │  Data Node (16 CPU / 128GB RAM / 10TB NVMe) │    │
│  │  PostgreSQL · Qdrant · MinIO · Redis        │    │
│  │  Vault · Grafana · Loki · Prometheus        │    │
│  └─────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────┘
```

### 10.2 Kubernetes Namespaces

```
stock-analyst/          # Core application
stock-analyst-data/     # Stateful services (PostgreSQL, Qdrant, MinIO, Redis)
stock-analyst-ml/       # ML services (Ollama, embeddings, reranker)
stock-analyst-infra/    # Traefik, Vault, Cert-Manager
stock-analyst-obs/      # Prometheus, Grafana, Loki, Sentry, LangSmith
```

### 10.3 Minimum Hardware Requirements

| Role | CPU | RAM | Storage | Notes |
|---|---|---|---|---|
| Control Plane | 8 cores | 32 GB | 500 GB SSD | etcd + orchestration |
| App Worker | 16 cores | 64 GB | 500 GB SSD | API + workers |
| ML Worker | 16 cores + GPU | 64 GB | 1 TB SSD | Ollama (A100/H100 optimal; RTX 4090 viable) |
| Data Node | 16 cores | 128 GB | 10 TB NVMe | All databases |

---

## 11. Observability & Quality Assurance

### 11.1 Key Metrics to Track

```
AGENT QUALITY METRICS:
- citation_coverage_rate          # % outputs with ≥95% cited claims (target: >98%)
- citation_enforcer_pass_rate     # % outputs passing on first attempt (target: >85%)
- hallucination_rate              # Quotes not found in source (target: <0.5%)
- average_retries_per_output      # Agent retry count (target: <1.2 avg)

PERFORMANCE METRICS:
- ingestion_latency_p95           # Document processing time (target: <120s for 100-page 10-K)
- retrieval_latency_p95           # RAG query time (target: <500ms)
- e2e_lynch_pitch_latency         # Full bull case generation (target: <90s)
- e2e_quarterly_update_latency    # Full quarterly analysis (target: <120s)

BUSINESS METRICS:
- coverages_per_tenant
- documents_per_coverage
- outputs_per_analyst_per_week
- llm_cost_per_output
- llm_cost_per_tenant_per_month
```

### 11.2 Evaluation Framework

```python
# Each agent has a golden evaluation set
# Example: Lynch Pitch Agent eval
eval_set = [
    {
        "input": {"coverage_id": "AAPL_TEST", "filings": [...known_docs...]},
        "expected_citations": [
            {"doc": "AAPL 10-K 2023", "section": "Business", "quote": "..."},
        ],
        "must_not_contain": ["will grow", "expected to", "analysts predict"],
        "must_contain_answers_for": [1, 2, 3, 4, 5, 6, 7, 8],  # all 8 questions
        "max_word_count": 800,
        "min_citation_coverage": 0.95
    }
]
```

---

## 12. Directory & Project Structure

```
stock-analyst/
├── apps/
│   ├── api/                         # FastAPI backend
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── coverages.py
│   │   │   ├── documents.py
│   │   │   ├── tasks.py
│   │   │   ├── outputs.py
│   │   │   └── admin.py
│   │   ├── middleware/
│   │   │   ├── auth.py              # Keycloak JWT validation
│   │   │   └── tenant.py            # Tenant context injection + RLS
│   │   ├── models/                  # SQLAlchemy + Pydantic models
│   │   └── services/
│   │       ├── llm_gateway.py       # LiteLLM wrapper
│   │       └── storage.py           # MinIO client
│   │
│   └── web/                         # Next.js 14 frontend
│       ├── app/
│       │   ├── (auth)/
│       │   ├── coverages/
│       │   │   ├── [id]/
│       │   │   │   ├── documents/
│       │   │   │   ├── research/
│       │   │   │   │   ├── industry/
│       │   │   │   │   ├── bull-case/
│       │   │   │   │   ├── bear-case/
│       │   │   │   │   └── quarterly/
│       │   │   │   └── kpis/
│       └── components/
│           ├── citation-tooltip.tsx
│           ├── kpi-chart.tsx
│           └── research-output.tsx
│
├── packages/
│   ├── agents/                      # LangGraph agent implementations
│   │   ├── orchestrator/
│   │   │   ├── agent.py
│   │   │   ├── graph.py             # LangGraph state graph
│   │   │   └── tools.py
│   │   ├── industry_analyst/
│   │   │   ├── agent.py
│   │   │   ├── prompts.py
│   │   │   ├── tools.py
│   │   │   └── schemas.py
│   │   ├── document_ingestion/
│   │   ├── lynch_pitch/
│   │   ├── munger_invert/
│   │   ├── earnings_monitor/
│   │   ├── kpi_tracker/
│   │   └── shared/
│   │       ├── citation_enforcer.py
│   │       ├── base_agent.py
│   │       └── message.py
│   │
│   ├── rag/                         # RAG pipeline
│   │   ├── ingestion/
│   │   │   ├── pipeline.py
│   │   │   ├── parsers/
│   │   │   │   ├── pdf_parser.py
│   │   │   │   ├── table_extractor.py
│   │   │   │   └── financial_normalizer.py
│   │   │   └── chunkers/
│   │   │       └── hierarchical.py
│   │   ├── retrieval/
│   │   │   ├── hybrid_retriever.py
│   │   │   └── reranker.py
│   │   └── connectors/
│   │       ├── sec_edgar.py
│   │       └── qdrant_client.py
│   │
│   └── shared/                      # Shared types, utils
│       ├── models.py
│       └── config.py
│
├── infra/
│   ├── docker-compose.yml           # Local development
│   ├── k8s/                         # Kubernetes manifests
│   │   ├── namespaces/
│   │   ├── deployments/
│   │   ├── services/
│   │   ├── configmaps/
│   │   └── pvcs/
│   ├── helm/                        # Helm charts
│   └── vault/                       # Vault policies
│
├── eval/                            # Agent evaluation suite
│   ├── datasets/
│   ├── runners/
│   └── reports/
│
├── migrations/                      # Alembic DB migrations
├── scripts/                         # Setup, seed, admin scripts
└── docs/                            # Technical documentation
```

---

## Summary: Build Order Checklist

| Phase | Duration | Key Deliverable |
|---|---|---|
| Phase 0 | 3 weeks | Authenticated multi-tenant infrastructure |
| Phase 1 | 4 weeks | End-to-end document ingestion + retrieval |
| Phase 2 | 6 weeks | All 5 research agents live with Citation Enforcer |
| Phase 3 | 4 weeks | Production-quality UX + streaming + exports |
| Phase 4 | 3 weeks | k3s cluster + security audit + DR runbook |
| **Total** | **~20 weeks** | **Production-ready on-premise platform** |

---

*Architecture version 1.0 — Stock Analyst AI Platform*  
*Self-hosted · Multi-tenant · Quote-first · Source-disciplined*
