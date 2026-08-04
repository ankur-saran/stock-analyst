# Stock Analyst AI — Detailed Development Plan
### From Requirements to Production Deployment

**Based on:** Stock_Analyst_AI_Architecture.md v1.0  
**Document version:** 1.0  
**Total estimated timeline:** ~20 weeks  

---

## Table of Contents

1. [Phase R — Requirements Analysis](#phase-r--requirements-analysis)
2. [Phase D — Design & Interface Contracts](#phase-d--design--interface-contracts)
3. [Phase 0 — Foundation Infrastructure](#phase-0--foundation-infrastructure-weeks-13)
4. [Phase 1 — Document Backbone](#phase-1--document-backbone-weeks-47)
5. [Phase 2 — Core Agents](#phase-2--core-agents-weeks-813)
6. [Phase 3 — Quality, UX & Intelligence](#phase-3--quality-ux--intelligence-weeks-1417)
7. [Phase 4 — Production Hardening](#phase-4--production-hardening-weeks-1820)
8. [Test Plans](#test-plans)
9. [Deployment Plan](#deployment-plan)
10. [Risk Register](#risk-register)

---

## Phase R — Requirements Analysis

### R.1 Functional Requirements Breakdown

Derived from the architecture document and the 5-step equity research methodology:

#### R.1.1 Coverage Management
| ID | Requirement | Source |
|---|---|---|
| FR-COV-01 | System shall allow users to create a stock coverage (project) identified by ticker + exchange | Architecture §6.1 |
| FR-COV-02 | Each coverage shall be scoped to a single tenant and inaccessible to other tenants | Architecture §8 |
| FR-COV-03 | Coverage status shall transition: `setup → active → archived` | Architecture §6.1 |
| FR-COV-04 | Coverage creation must trigger a prerequisite check before any agent task can run | Architecture §4, Agent 1 |

#### R.1.2 Document Ingestion
| ID | Requirement | Source |
|---|---|---|
| FR-DOC-01 | System shall auto-fetch 10-K, 10-Q, 8-K from SEC EDGAR by ticker + year | Architecture §4, Agent 3 |
| FR-DOC-02 | Users shall be able to upload custom PDFs (transcripts, presentations, notes) | Architecture §4, Agent 3 |
| FR-DOC-03 | Every ingested chunk must carry: document_name, filing_type, period, page_number, section_name | Architecture §7.1 |
| FR-DOC-04 | Duplicate documents (same hash) must be rejected silently | Architecture §7.1 |
| FR-DOC-05 | Documents with <50% text extraction rate must be flagged for manual review | Architecture §7.1 |
| FR-DOC-06 | Tables must be extracted as structured JSON, not flattened text | Architecture §4, Agent 3 |
| FR-DOC-07 | Financial figures must be normalized to a standard unit (USD millions, period label) | Architecture §4, Agent 3 |

#### R.1.3 Agent Research Workflow
| ID | Requirement | Source |
|---|---|---|
| FR-AGT-01 | Orchestrator shall route every user intent to the correct specialist agent | Architecture §4, Agent 1 |
| FR-AGT-02 | Industry analysis must run once per industry and be reused across all coverages in that industry | Architecture §4, Agent 2 |
| FR-AGT-03 | Lynch Pitch shall answer exactly 8 structured questions using only coverage documents | Architecture §4, Agent 4 |
| FR-AGT-04 | Munger Invert shall produce adversarial analysis with footnote and off-balance-sheet search | Architecture §4, Agent 5 |
| FR-AGT-05 | Earnings Monitor shall compare prior guidance quotes to actual results, quote-for-quote | Architecture §4, Agent 6 |
| FR-AGT-06 | KPI Tracker shall maintain time-series KPIs auto-detected from industry type | Architecture §4, Agent 7 |
| FR-AGT-07 | No agent may state a factual claim without a retrievable citation ([Doc, Section]: "quote") | Architecture §3.1 |
| FR-AGT-08 | Citation coverage must be ≥95% for any output to be approved | Architecture §4, Citation Enforcer |
| FR-AGT-09 | Citation Enforcer shall retry agent up to 3 times before surfacing a PARTIAL flag to user | Architecture §4, Citation Enforcer |

#### R.1.4 KPI & Earnings Tracking
| ID | Requirement | Source |
|---|---|---|
| FR-KPI-01 | System shall auto-detect relevant KPIs based on industry type (SaaS, Retail, Banks, etc.) | Architecture §4, Agent 7 |
| FR-KPI-02 | Every KPI data point must carry a citation to its source document | Architecture §4, Agent 7 |
| FR-KPI-03 | Restatements must be logged with both old and new values | Architecture §4, Agent 7 |
| FR-KPI-04 | Management credibility score must accumulate across quarters | Architecture §4, Agent 6 |
| FR-KPI-05 | Earnings calendar integration shall auto-trigger quarterly update tasks | Architecture §9 Phase 3 |

#### R.1.5 Multi-Tenancy
| ID | Requirement | Source |
|---|---|---|
| FR-MT-01 | Each tenant shall have isolated PostgreSQL data via Row-Level Security | Architecture §8.1 |
| FR-MT-02 | Each tenant shall have a dedicated Qdrant collection | Architecture §8.1 |
| FR-MT-03 | Each tenant shall have a dedicated MinIO bucket | Architecture §8.1 |
| FR-MT-04 | RBAC shall enforce four roles: viewer, analyst, senior_analyst, admin | Architecture §8.2 |

#### R.1.6 Frontend
| ID | Requirement | Source |
|---|---|---|
| FR-FE-01 | Research outputs must stream in real-time to the frontend via WebSockets | Architecture §9 Phase 3 |
| FR-FE-02 | Citation hover/click must open the source document at the cited page | Architecture §9 Phase 2 |
| FR-FE-03 | KPI dashboard must render time-series charts per metric | Architecture §9 Phase 2 |
| FR-FE-04 | Analyst notes editor must support citation linking (Tiptap) | Architecture §9 Phase 3 |
| FR-FE-05 | PDF export must be available for any research output | Architecture §9 Phase 3 |

---

### R.2 Non-Functional Requirements

| ID | Category | Requirement | Target |
|---|---|---|---|
| NFR-PERF-01 | Performance | Document ingestion for 100-page 10-K | <120 seconds |
| NFR-PERF-02 | Performance | RAG retrieval latency (p95) | <500ms |
| NFR-PERF-03 | Performance | Lynch Pitch end-to-end generation | <90 seconds |
| NFR-PERF-04 | Performance | Quarterly update end-to-end generation | <120 seconds |
| NFR-PERF-05 | Performance | Concurrent analysts supported | ≥10 simultaneous |
| NFR-SEC-01 | Security | Data at rest encryption | AES-256 |
| NFR-SEC-02 | Security | Data in transit encryption | TLS 1.3 |
| NFR-SEC-03 | Security | LLM API key rotation | Quarterly, via Vault |
| NFR-SEC-04 | Security | Tenant cross-contamination | Zero tolerance |
| NFR-SEC-05 | Security | External LLM data exposure | Zero PII without opt-in |
| NFR-QA-01 | Quality | Citation coverage per output | ≥95% |
| NFR-QA-02 | Quality | Citation Enforcer pass rate (first attempt) | >85% |
| NFR-QA-03 | Quality | Hallucination rate (quote not found in source) | <0.5% |
| NFR-QA-04 | Quality | Average retries per output | <1.2 |
| NFR-REL-01 | Reliability | All stateful services backed up | Daily snapshots |
| NFR-OBS-01 | Observability | Every agent call traced end-to-end | LangSmith |
| NFR-OBS-02 | Observability | LLM cost tracked per tenant / coverage | LiteLLM |
| NFR-DEP-01 | Deployment | Fully self-hosted, no mandatory cloud dependency | On-premise k3s |
| NFR-DEP-02 | Deployment | Air-gapped operation mode available | Llama 3.1 local fallback |

---

### R.3 Dependency Map (Build Order Logic)

The following chains represent hard prerequisites — no step can start until all its parents are complete:

```
[Infra: Docker Compose] 
    → [DB Schema + Migrations]
    → [Auth Middleware (Keycloak)]
    → [Tenant Middleware (RLS)]
    → [FastAPI skeleton + health endpoints]

[FastAPI] + [Qdrant] + [MinIO] + [nomic-embed model]
    → [Document Ingestion Pipeline]
    → [SEC EDGAR Connector]
    → [Chunking + Embedding + Indexing]
    → [Hybrid Retriever (dense + sparse + reranker)]

[Hybrid Retriever]
    → [Citation Enforcer] (needs RAG to verify quote existence)
    → [Orchestrator Agent] (needs Citation Enforcer in loop)

[Orchestrator] + [Retriever] + [Citation Enforcer]
    → [Industry Analyst Agent]
    → [Lynch Pitch Agent]
    → [Munger Invert Agent]

[Document Ingestion] + [Citation Enforcer]
    → [KPI Tracker Agent]
    → [Earnings Monitor Agent]

[All Agents] → [WebSocket streaming] → [Frontend views]
[All Agents] → [LangSmith tracing] → [Observability dashboards]
```

---

### R.4 Stakeholder Analysis

| Stakeholder | Primary Concern | Acceptance Criteria |
|---|---|---|
| Equity Analyst | Research quality, citation accuracy, speed | 95%+ cited outputs; <90s latency; document click-through works |
| Senior Analyst | Output review/approval workflow | PARTIAL flag surfaced clearly; 1-click approve/reject |
| Tenant Admin | Cost visibility, user management | Per-tenant cost dashboard; RBAC enforced |
| IT / Infrastructure | Self-hosted, minimal cloud dependency, backup | k3s on-prem; daily Velero backups; Vault for secrets |
| Compliance / Legal | Data residency, audit trail, no data leakage | Immutable audit log; air-gapped mode; no PII to external LLMs |

---

### R.5 Risk Register (Requirements Phase)

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| SEC EDGAR API rate limits during bulk ingestion | High | Medium | Implement exponential backoff; cache raw filings in MinIO before processing |
| PDF extraction quality for scanned documents | High | High | Unstructured.io fallback for <50% text coverage; manual review queue |
| Citation Enforcer retry storms (agent repeatedly fails) | Medium | High | Hard cap at 3 retries; PARTIAL flag with human review; monitor retry rate daily |
| LLM API cost overruns during development | Medium | Medium | LiteLLM cost caps per tenant; local Llama for dev/test runs |
| Qdrant cross-tenant data leak via misconfigured filter | Low | Critical | Integration test: assert zero cross-tenant retrieval on every deploy |
| Keycloak complexity delaying auth integration | Medium | High | Set up Keycloak realm with mock users in Week 1; never block on it |

---

## Phase D — Design & Interface Contracts

Before writing code, align on these interface contracts across teams/modules.

### D.1 Agent Message Contract (Finalize Before Phase 2)

All inter-agent messages use `AgentMessage` (Architecture §3.3). Validate these fields are present in every dispatch:

- `message_id` — UUID, generated at dispatch time
- `tenant_id` — injected from request context, never from agent
- `coverage_id` — from the active coverage session
- `requires_citation: True` — hardcoded for all research agents
- `llm_preference` — set by Orchestrator based on task type (heavy reasoning → PRIMARY/Claude, extraction → SECONDARY/GPT-4o, air-gapped → LOCAL/Llama)

### D.2 Citation Format Contract

Every factual claim in every agent output must conform to:

```
[{document_name}, {section_or_page}]: "{exact_quote}" → {interpretation}
```

- `document_name` — matches the `Document.file_name` in PostgreSQL
- `exact_quote` — must be retrievable via BM25 exact search in Qdrant
- `interpretation` — analyst's reading of the quote (may be omitted for pure data extraction)

The Citation Enforcer validates that `exact_quote` is found in the vector store before approving. This means the ingestion pipeline must index every sentence reliably.

### D.3 API Contract (FastAPI → Frontend)

Streaming endpoint for agent output:

```
WebSocket: /ws/tasks/{task_id}
Messages:
  { "type": "progress", "step": "retrieving_citations", "pct": 30 }
  { "type": "chunk", "content": "...", "citations": [...] }
  { "type": "complete", "output_id": "...", "citation_coverage_pct": 0.97 }
  { "type": "error", "code": "CITATION_ENFORCER_FAIL", "retry_count": 2 }
```

### D.4 KPI Normalization Contract

| Raw value | Normalized form |
|---|---|
| "$1.23B" | `{ value: 1230, unit: "USD_millions", period: "FY2024" }` |
| "12.3%" | `{ value: 12.3, unit: "percentage", period: "Q3 2024" }` |
| "4.5M shares" | `{ value: 4500000, unit: "count", period: "Q3 2024" }` |

Restatements: if same `(coverage_id, kpi_name, period)` already exists with a different value, log both and set `is_restated: True`.

---

## Phase 0 — Foundation Infrastructure (Weeks 1–3)

### Goal
Core infrastructure running locally. No agents yet. Any developer can clone and boot the system.

### Week 1 — Repository & Local Services

#### Step 0.1 — Monorepo Setup
- [ ] Initialize monorepo: `stock-analyst/` with structure per Architecture §12
- [ ] Configure workspace: Python packages (`pyproject.toml` per package), Node workspace (`package.json`)
- [ ] `.editorconfig`, `.gitignore`, `pre-commit` hooks (ruff, mypy, eslint)
- [ ] Environment template: `.env.example` with all required variables documented

**Acceptance:** `git clone && docker compose up` runs without manual steps beyond copying `.env`

#### Step 0.2 — Docker Compose Stack
Define `infra/docker-compose.yml` with all local services:

```yaml
services:
  postgres:    # PostgreSQL 16 with health check
  redis:       # Redis 7 with AOF persistence
  qdrant:      # Qdrant latest with persistence volume
  minio:       # MinIO with default bucket creation
  keycloak:    # Keycloak 24 with realm import on boot
  ollama:      # Ollama with nomic-embed-text-v1.5 pre-pulled
  litellm:     # LiteLLM gateway with config.yaml
  langsmith:   # LangSmith local (or configure cloud endpoint)
```

**Acceptance:** All services healthy, `docker compose ps` shows all green

#### Step 0.3 — Database Schema & Migrations
Using Alembic. Tables to create (in order, respecting FK dependencies):

1. `tenants` — id, name, plan, settings JSONB, created_at
2. `users` — id, tenant_id FK, email, role, created_at
3. `industries` — id, name, primer_content, created_at
4. `coverages` — id, tenant_id FK, ticker, company_name, exchange, industry_id FK, created_by FK, status, document_count, last_updated
5. `documents` — id, coverage_id FK, tenant_id FK, file_name, filing_type, period, source, source_url, storage_path, page_count, chunk_count, ingested_at, quality_score
6. `research_outputs` — id, coverage_id FK, output_type, content, citations JSONB, citation_coverage_pct, approved_by_enforcer, llm_used, tokens_used, generated_at, version
7. `kpi_timeseries` — id, coverage_id FK, kpi_name, period, period_type, value, unit, citation JSONB, is_restated, restatement_note (partitioned by coverage_id)
8. `agent_audit_log` — id, tenant_id, coverage_id, agent_name, action, input_hash, output_id, llm_used, tokens_used, latency_ms, created_at (append-only, no UPDATE/DELETE)
9. `task_queue` — id, coverage_id FK, tenant_id FK, task_type, status, celery_task_id, created_at, started_at, completed_at, error

**Enable RLS on all tenant-scoped tables immediately after creation.** Migration file must include the policy creation (see Architecture §8.1).

**Acceptance:** `alembic upgrade head` runs cleanly; psql shows all tables with RLS enabled

### Week 2 — Auth & API Skeleton

#### Step 0.4 — Keycloak Realm Setup
- [ ] Create realm: `stock-analyst`
- [ ] Create client: `stock-analyst-api` (confidential, service account)
- [ ] Create client: `stock-analyst-web` (public, PKCE)
- [ ] Define roles: `viewer`, `analyst`, `senior_analyst`, `admin`
- [ ] Seed test users: one per role per test tenant
- [ ] Export realm config as `infra/keycloak/realm-export.json` — imported on container start

**Acceptance:** Can log in as each test user via Keycloak UI; JWT contains correct role claim

#### Step 0.5 — FastAPI Skeleton
Build `apps/api/` with:

- `main.py` — lifespan events, middleware registration, router inclusion
- `middleware/auth.py` — validate Keycloak JWT; extract `user_id`, `tenant_id`, `role` into request state
- `middleware/tenant.py` — execute `SET LOCAL app.current_tenant_id = '{tenant_id}'` on every DB connection (activates RLS)
- `routers/health.py` — `GET /health` (no auth), `GET /health/deep` (checks DB, Redis, Qdrant, MinIO connectivity)
- `routers/admin.py` — stub endpoints returning 501 for now

**Acceptance:** `GET /health/deep` returns 200 with all service statuses; unauthed request to protected endpoint returns 401; wrong tenant cannot read another tenant's data (write an integration test to prove this)

#### Step 0.6 — LiteLLM Gateway Configuration
Configure `infra/litellm/config.yaml`:

```yaml
model_list:
  - model_name: primary
    litellm_params:
      model: anthropic/claude-opus-4-8  # or claude-sonnet-4-6 for dev
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: secondary
    litellm_params:
      model: openai/gpt-4o
      api_key: os.environ/OPENAI_API_KEY

  - model_name: local
    litellm_params:
      model: ollama/llama3.1:70b
      api_base: http://ollama:11434

router_settings:
  fallbacks: [{"primary": ["local"]}]
  context_window_fallbacks: [{"primary": ["secondary"]}]
```

**Acceptance:** Curl each model via LiteLLM proxy; confirm token usage is logged

### Week 3 — Frontend Shell & CI

#### Step 0.7 — Next.js Auth Shell
Build `apps/web/` with:

- Auth provider: NextAuth.js with Keycloak provider (OIDC)
- Protected route wrapper: redirect to login if no valid session
- Layout: sidebar navigation (Coverages, Admin — greyed out stubs)
- Role-aware rendering: hide Admin link unless role = `admin`

**Acceptance:** Login/logout flow works; protected pages redirect; role-based nav hides correct items

#### Step 0.8 — CI Pipeline (Gitea Actions)
`.gitea/workflows/ci.yml`:

```yaml
on: [push, pull_request]
jobs:
  lint-python:    ruff check + mypy (strict)
  lint-frontend:  eslint + tsc --noEmit
  test-unit:      pytest packages/ (excluding integration)
  test-infra:     docker compose up --wait + health check
  migration-test: alembic upgrade head on fresh DB
```

**Acceptance:** All CI checks pass on a clean branch; PRs blocked by failing checks

#### Step 0.9 — MinIO Bucket Policies
Via `scripts/setup_minio.py`:

- Create bucket `stocks-{tenant_id}` for each test tenant
- Attach bucket policy: only the service account for that tenant can read/write
- Pre-signed URL TTL: 15 minutes

**Acceptance:** Service account for tenant A cannot list or read tenant B's bucket

---

## Phase 1 — Document Backbone (Weeks 4–7)

### Goal
Full document ingestion pipeline working end-to-end. Upload any SEC filing → chunked, embedded, indexed, retrievable in <2 minutes.

### Week 4 — SEC Connector & PDF Parser

#### Step 1.1 — SEC EDGAR Connector
File: `packages/rag/connectors/sec_edgar.py`

```python
class SECEdgarConnector:
    async def fetch_filing(self, ticker: str, form_type: str, year: int) -> FilingResult
    async def list_filings(self, ticker: str, form_type: str) -> list[FilingMeta]
    async def download_to_minio(self, filing_url: str, coverage_id: str) -> str  # returns MinIO path
```

- Use SEC EDGAR Full-Text Search API (no API key needed, but implement polite rate limiting: max 10 req/s)
- Store raw downloaded file in MinIO at `/tenants/{tid}/coverages/{cid}/raw/`
- Register document in PostgreSQL `documents` table immediately after download (before processing)

**Acceptance:** Fetch AAPL 10-K 2023 → file in MinIO → document record in DB

#### Step 1.2 — PDF Parser
File: `packages/rag/ingestion/parsers/pdf_parser.py`

Two-stage approach:
1. **PyMuPDF** (`fitz`) — fast, tries text extraction first; extracts page-level text blocks with page numbers
2. **Unstructured.io** — fallback if PyMuPDF yields <50% text coverage (scanned PDFs, embedded images)

Output per page:
```python
@dataclass
class ParsedPage:
    page_number: int
    text_blocks: list[TextBlock]  # each block has bbox, font, text
    tables: list[str]             # raw table text (Docling handles structured version)
    text_coverage_pct: float      # ratio of expected vs extracted text
```

**Acceptance:** Parse AAPL 10-K 2023 (100+ pages); text coverage >90%; page numbers preserved

#### Step 1.3 — Table Extractor
File: `packages/rag/ingestion/parsers/table_extractor.py`

Uses Docling:
- Detects tables in PDF pages
- Outputs each table as: (a) structured JSON (row/col/value), (b) markdown representation
- Tags each table with: `{page_number, table_index, caption}` if detectable

**Acceptance:** Extract income statement from AAPL 10-K as JSON with correct row/col structure

### Week 5 — Financial Normalizer & Chunker

#### Step 1.4 — Financial Normalizer
File: `packages/rag/ingestion/parsers/financial_normalizer.py`

Handles:
- Currency normalization: "$", "USD", "EUR" → ISO code + value in base units
- Unit normalization: "million", "M", "MM", "billion", "B" → value * multiplier stored in `USD_millions`
- Period normalization: "fiscal year 2024", "FY24", "twelve months ended Dec 31, 2024" → `FY2024`
- Quarter normalization: "third quarter 2024", "Q3'24", "three months ended Sep 30, 2024" → `Q3 2024`

**Acceptance:** Unit tests covering 20+ real-world format variations from SEC filings

#### Step 1.5 — Hierarchical Chunker
File: `packages/rag/ingestion/chunkers/hierarchical.py`

Two-level chunking (Architecture §7.1 Step 6):

```
Parent chunks: full sections (~2000 tokens)
  → preserve structural context (MD&A, Risk Factors, Financial Statements)
Child chunks: paragraphs/sentences (~200 tokens)
  → used for embedding and exact citation retrieval
  → each child carries: parent_chunk_id (for hydration at retrieval)

Table chunks: each table as one chunk (JSON + markdown representation)
  → tagged separately so table retrieval doesn't mix with prose
```

Metadata on every chunk:
```python
chunk_metadata = {
    "document_id": str,
    "document_name": str,
    "filing_type": str,
    "period": str,
    "page_number": int,
    "section_name": str,
    "chunk_type": "parent" | "child" | "table",
    "parent_chunk_id": str | None,
    "tenant_id": str,
    "coverage_id": str,
    "char_start": int,
    "char_end": int,
}
```

**Acceptance:** Chunk AAPL 10-K → verify parent/child relationships preserved; every child carries all metadata fields

### Week 6 — Embedding, Indexing & Retrieval

#### Step 1.6 — Embedding Pipeline
File: `packages/rag/ingestion/pipeline.py`

- Model: `nomic-embed-text-v1.5` via Ollama (`http://ollama:11434/api/embeddings`)
- Batch embedding: 32 chunks per API call to Ollama (tune for throughput)
- Vector dimension: 768
- Store in Qdrant collection `tenant_{tenant_id}` with full metadata payload

**Acceptance:** Embed 500 chunks from a 10-K in <30 seconds; vectors retrievable from Qdrant

#### Step 1.7 — BM25 Sparse Index
The BM25 index is required for exact quote retrieval (critical for Citation Enforcer validation).

Options:
- **Qdrant sparse vectors** — use Qdrant's built-in sparse vector support with BM25 weights (preferred; keeps everything in one store)
- Alternative: `rank_bm25` library with an in-memory index, persisted to Redis per coverage

Implement as Qdrant sparse vectors. Each chunk gets both a dense vector (embedding) and sparse vector (BM25 weights over tokens).

**Acceptance:** Query `"revenue increased 12%" ` → BM25 retrieves the exact paragraph containing that phrase ranked #1

#### Step 1.8 — Hybrid Retriever
File: `packages/rag/retrieval/hybrid_retriever.py`

Implement the `HybridRetriever` from Architecture §7.2:

1. Dense search (Qdrant cosine similarity, top 20)
2. Sparse BM25 search (top 20)
3. Reciprocal Rank Fusion (combine, deduplicate)
4. CrossEncoder reranking (top 8 after reranking)
5. Parent hydration (fetch parent chunk for context if child selected)

All searches **must** include `{tenant_id, coverage_id}` filter — never retrieve without these filters.

**Acceptance:** 
- Retrieve top-8 chunks for query "gross margin trend" from AAPL coverage
- Verify zero results returned when querying with wrong `tenant_id`
- Latency <500ms at p95

### Week 7 — Ingestion API, Celery, and Document UI

#### Step 1.9 — Celery Ingestion Task
File: `apps/api/tasks/ingestion.py`

```python
@celery_app.task(bind=True, max_retries=3)
def ingest_document(self, document_id: str, coverage_id: str, tenant_id: str):
    # 1. Load raw file from MinIO
    # 2. Hash check (skip if already indexed)
    # 3. Parse PDF (PyMuPDF → Unstructured.io fallback)
    # 4. Extract tables (Docling)
    # 5. Normalize financials
    # 6. Hierarchical chunking
    # 7. Embed chunks (nomic-embed-text)
    # 8. Index in Qdrant (dense + sparse)
    # 9. Update document record: chunk_count, quality_score, status=indexed
    # 10. Log to agent_audit_log
```

**Acceptance:** POST a document → Celery picks up task → document indexed in <120 seconds for 100-page PDF

#### Step 1.10 — REST Endpoints for Documents
Add to `apps/api/routers/documents.py`:

```
POST /api/v1/coverages/{id}/documents        # Upload file or provide SEC EDGAR params
GET  /api/v1/coverages/{id}/documents        # List with status, chunk_count, quality_score
DELETE /api/v1/coverages/{id}/documents/{doc_id}  # Remove from Qdrant + MinIO + DB
GET  /api/v1/tasks/{task_id}                 # Poll ingestion task status
```

#### Step 1.11 — Document Management UI
Pages to build in Next.js:

- `/coverages/[id]/documents` — list all documents with status badges (Indexing / Indexed / Failed / Review Needed)
- Upload component: drag-and-drop PDF OR SEC auto-fetch form (ticker + form type + year)
- Quality warning banner: highlight documents with quality_score <0.7
- Delete with confirmation dialog

**Acceptance:** Upload a 10-K via UI → watch status change to Indexed → can see chunk count

---

## Phase 2 — Core Agents (Weeks 8–13)

### Goal
All 7 agents (Orchestrator, Industry Analyst, Document Ingestion, Lynch Pitch, Munger Invert, Earnings Monitor, KPI Tracker) working with Citation Enforcer. Full 5-step research workflow automated.

### Week 8 — LangGraph State Machine & Orchestrator

#### Step 2.1 — LangGraph Coverage Workflow
File: `packages/agents/orchestrator/graph.py`

Build the state machine from Architecture §3.4:

```python
class CoverageState(TypedDict):
    coverage_id: str
    tenant_id: str
    current_step: str
    prerequisites_met: bool
    missing_prerequisites: list[str]
    industry_loaded: bool
    documents_loaded: bool
    lynch_pitch_complete: bool
    munger_invert_complete: bool
    task_history: list[dict]
    error: str | None
```

Nodes: `coverage_init`, `industry_analysis`, `doc_ingestion`, `lynch_pitch`, `munger_invert`, `citation_validation`, `quarterly_monitor`

Edges include conditional routing based on prerequisites (e.g., cannot run `lynch_pitch` if `documents_loaded = False`).

**Acceptance:** Run a mock coverage through the state machine; verify state transitions are correct and prerequisites block execution

#### Step 2.2 — Orchestrator Agent
File: `packages/agents/orchestrator/agent.py`

Implement the system prompt and tools from Architecture §4, Agent 1:

- Tools: `check_coverage_exists`, `check_industry_loaded`, `check_filing_count`, `list_available_agents`, `dispatch_task`, `get_task_status`
- Output must always be JSON conforming to the plan schema
- If prerequisites missing, return `PREREQUISITE_MISSING` with exact missing items listed

**Acceptance:** Send "run bull case for AAPL" without filings loaded → Orchestrator returns PREREQUISITE_MISSING listing exactly what's needed

#### Step 2.3 — Citation Enforcer
File: `packages/agents/shared/citation_enforcer.py`

Implement all 6 validation checks (Architecture §4, Citation Enforcer):

1. `check_citation_coverage` — count citations vs factual claims; reject if <95%
2. `check_quote_format` — regex validate `[Doc, Section]: "quote"` format on every citation
3. `check_quote_exists_in_rag` — BM25 search for the exact quote; fail if not found (hallucination check)
4. `check_no_unsourced_numbers` — detect numeric values not followed by a citation
5. `check_no_future_speculation` — flag "will", "expects to", "is expected to" unless sourced to a management quote
6. `check_inference_labeling` — inferred statements must be marked `(inferred from [source])`

Retry logic: build `retry_prompt` that lists exactly which checks failed and what the agent must fix.

**Acceptance:** Submit a deliberately hallucinated output → Citation Enforcer returns `approved=False` with exact failed checks; submit a clean output → approved

### Week 9 — Industry Analyst Agent

#### Step 2.4 — Industry Analyst Agent
File: `packages/agents/industry_analyst/agent.py`

Implement Agent 2 (Architecture §4):

- Tools: `web_search` (Tavily), `fetch_url`, `rag_search` (industry scope), `save_industry_primer`
- System prompt enforces 6-section structure + 5-bullet investor synthesis
- LLM: PRIMARY (Claude Opus) with extended thinking enabled
- Output schema: `IndustryPrimer` (Architecture §4, Agent 2)

Industry primer is shared across tenants for the same industry — store with `industry_id` key, no `tenant_id` (but sourced documents are tenant-scoped).

**Acceptance:** Run industry analysis for "semiconductor capital equipment" → output has all 6 sections, 5 bullets, every claim cited, Citation Enforcer approves

#### Step 2.5 — Industry Primer UI
Page: `/coverages/[id]/research/industry`

- Rendered markdown with inline citation superscripts
- Citation tooltip on hover: shows document name, section, exact quote
- Section jump links in sidebar
- "Run Industry Analysis" button with prerequisite check feedback

### Weeks 10–11 — Lynch Pitch & Munger Invert Agents

#### Step 2.6 — Lynch Pitch Agent
File: `packages/agents/lynch_pitch/agent.py`

Implement Agent 4 (Architecture §4):

- Tools: `rag_search` (coverage scope), `get_financial_summary`, `get_management_credibility_score`, `validate_citations`, `save_bull_case`
- Enforces 8-question structure; each answer is an `AnswerWithCitation` object
- Refuses to answer if no supporting quote found: outputs "Not found in uploaded documents."
- LLM: PRIMARY (Claude Opus)

```python
class AnswerWithCitation(BaseModel):
    question_number: int
    answer_text: str
    citations: list[Citation]
    citation_coverage_pct: float
    not_found_items: list[str]  # claims explicitly stated as not found
```

**Acceptance:** Run Lynch Pitch on a company with 3 years of 10-Ks → all 8 questions answered; 95%+ citation coverage; Citation Enforcer approves; "Not found" appears where legitimately unavailable

#### Step 2.7 — Munger Invert Agent
File: `packages/agents/munger_invert/agent.py`

Implement Agent 5 (Architecture §4):

- Extends Lynch Pitch tools with: `search_risk_factors`, `search_footnotes`, `compare_narrative_to_data`
- `search_footnotes` does targeted RAG in note sections only (filter by `section_name` containing "footnotes" or "notes to financial statements")
- `compare_narrative_to_data`: retrieves management quotes about a KPI from prior periods and compares to actual reported values
- LLM: PRIMARY (Claude Opus)

**Acceptance:** Run Munger Invert on same company → adversarial framing; footnotes referenced; management narrative vs data divergence identified where it exists

#### Step 2.8 — Bull/Bear UI
Page: `/coverages/[id]/research/bull-case` and `/coverages/[id]/research/bear-case`

- Side-by-side comparison view (desktop) / tabs (mobile)
- Each Q&A section collapsible
- Citation modal: click citation → document viewer opens at exact page
- Citation coverage % badge per section
- "PARTIAL — Manual Review Required" banner if Citation Enforcer flagged

### Weeks 12–13 — KPI Tracker & Earnings Monitor Agents

#### Step 2.9 — KPI Tracker Agent
File: `packages/agents/kpi_tracker/agent.py`

Implement Agent 7 (Architecture §4):

- `detect_industry_kpis(industry_id)` — maps industry type to KPI list (define a config file: `kpi_definitions.yaml` with industry → KPI mapping)
- `extract_kpis_from_doc` — structured extraction using SECONDARY LLM (GPT-4o); outputs exact quoted value + citation per KPI
- `normalize_kpi` — applies Financial Normalizer (Step 1.4)
- `upsert_kpi_timeseries` — inserts or updates `kpi_timeseries` table; detects restatements
- `compute_yoy_change` — computes year-over-year % delta

**Acceptance:** Run KPI extraction on 4 quarters of a SaaS company → ARR, NRR, Churn populated in time-series table; each row has citation; restatement detected if present

#### Step 2.10 — Earnings Monitor Agent
File: `packages/agents/earnings_monitor/agent.py`

Implement Agent 6 (Architecture §4):

- 3-section structured output: Guidance vs Reality, KPI Analysis, What Actually Changed
- Dual-citation format: every claim cites BOTH the prior-period source AND the current-period source
- `compare_management_language` — scans historical guidance extracts for recurring phrases (excuse detection)
- `update_credibility_score` — persists per-quarter management credibility to PostgreSQL
- LLM: PRIMARY (Claude Opus); guidance comparison is reasoning-heavy

**Acceptance:** Process a new 10-Q after loading a prior quarter → guidance items from prior Q identified; current-period actuals retrieved; variance calculated; credibility score persisted

#### Step 2.11 — KPI Dashboard
Page: `/coverages/[id]/kpis`

- KPI selector: shows industry-relevant KPIs
- Time-series chart (Recharts) per KPI: quarterly and annual lines
- Restatement indicator: dotted line connecting original and restated values
- Hover tooltip: shows citation details for any data point

---

## Phase 3 — Quality, UX & Intelligence (Weeks 14–17)

### Goal
Production-ready quality. Analyst-grade UX. Streaming. Exports. Automated earnings monitoring.

### Week 14 — Citation Accuracy & Hallucination Evaluation

#### Step 3.1 — Golden Evaluation Dataset
Directory: `eval/datasets/`

Create manually-curated eval sets for each agent (minimum 5 examples per agent):

```json
{
  "agent": "lynch_pitch",
  "test_cases": [
    {
      "coverage_id": "AAPL_EVAL_2023",
      "documents": ["aapl_10k_2023.pdf"],
      "expected_citations": [
        { "doc": "AAPL 10-K 2023", "section": "Business", "min_quote_length": 20 }
      ],
      "must_answer_questions": [1,2,3,4,5,6,7,8],
      "must_not_contain": ["will grow", "analysts predict", "expected to"],
      "min_citation_coverage": 0.95,
      "max_word_count": 900
    }
  ]
}
```

#### Step 3.2 — Automated Evaluation Runner
File: `eval/runners/run_eval.py`

- Runs each agent against all test cases
- Computes: citation_coverage_pct, hallucination_rate, format_compliance, latency
- Outputs HTML report to `eval/reports/`
- Integrates with LangSmith evaluation API for trace-level analysis
- CI gate: evaluation must pass before Phase 3 is considered complete

**Acceptance:** All agents score ≥95% citation coverage on golden eval set; hallucination_rate <0.5%

#### Step 3.3 — Hallucination Detection
Enhance Citation Enforcer `check_quote_exists_in_rag`:

- Current: checks if quote string is found in Qdrant
- Enhance: use embedding similarity to verify the quote is semantically close to its source chunk (catches paraphrased misquotes)
- Log every hallucination to `agent_audit_log` with `action: "hallucination_detected"`

### Week 15 — Streaming & Advanced UI

#### Step 3.4 — WebSocket Streaming
File: `apps/api/routers/tasks.py`

- `WebSocket /ws/tasks/{task_id}` — streams agent progress events
- LangGraph node callbacks emit progress events to Redis pub/sub channel `task:{task_id}`
- WebSocket handler subscribes to that channel and forwards to client
- Events: `progress`, `chunk` (agent text as it generates), `citation_found`, `enforcer_result`, `complete`, `error`

**Acceptance:** Open Lynch Pitch task via WebSocket → see text stream in real-time; see citation events as they're found; final event shows citation_coverage_pct

#### Step 3.5 — Coverage Dashboard
Page: `/coverages` (enhanced)

- Portfolio view: all coverages as cards with last-update date, document count, last KPI snapshot
- Status indicators: bull/bear case status, last quarterly update date
- Quick filters: by industry, by update age
- Create coverage modal with ticker auto-complete

#### Step 3.6 — Analyst Notes Editor
Component: `apps/web/components/notes-editor.tsx`

- Tiptap editor with custom citation extension
- Citation extension: type `@cite` → search coverage documents → insert `[Doc, Section]: "quote"` inline
- Export notes as part of PDF report

### Week 16 — Export & Notifications

#### Step 3.7 — PDF Report Export
File: `apps/api/services/report_generator.py`

- Generate PDF from: Coverage summary, Industry Primer, Lynch Pitch, Munger Invert, latest Quarterly Update
- Use `WeasyPrint` or `Playwright` (headless browser screenshot) for PDF rendering
- Inline citation references as footnotes
- Endpoint: `GET /api/v1/coverages/{id}/report.pdf`

**Acceptance:** Download PDF for a complete coverage; all sections present; citations formatted as footnotes; no broken references

#### Step 3.8 — Earnings Calendar & Auto-Trigger
File: `apps/api/tasks/scheduler.py`

- Celery Beat scheduled task: daily at 6am, check SEC EDGAR for new filings for all active coverages
- If new 10-Q or 10-K found: auto-ingest + auto-trigger Earnings Monitor
- Result: notification event sent to tenant's analyst users

#### Step 3.9 — Notification System
- Email notification: send summary when quarterly update completes (SMTP, configurable)
- In-app notification: WebSocket push to all open browser sessions for the tenant
- Notification content: "New earnings processed for [TICKER] — click to view quarterly update"

### Week 17 — LLM Cost Dashboard & Performance Tuning

#### Step 3.10 — LLM Cost Dashboard
Page: `/admin/usage` (admin only)

- Per-tenant monthly cost (from LiteLLM callback logs)
- Per-coverage cost breakdown
- Per-agent cost breakdown
- Token usage over time (chart)
- Alert threshold: admin configures max spend per tenant per month

#### Step 3.11 — Performance Tuning
Targets from NFR:
- Ingestion: 100-page 10-K in <120s → profile, identify bottleneck (likely embedding), optimize batch size
- Retrieval: p95 <500ms → add Qdrant index tuning, pre-warm embedding model
- Lynch Pitch e2e: <90s → reduce RAG round-trips, parallel tool calls where safe
- Quarterly Update e2e: <120s → cache prior guidance extract between runs

Run load test: 10 concurrent analysts each running a Lynch Pitch → all complete in <90s

---

## Phase 4 — Production Hardening (Weeks 18–20)

### Goal
On-premise k3s cluster. Security-audited. Backup-tested. Documented. Ready for real analysts.

### Week 18 — k3s Cluster & Helm Charts

#### Step 4.1 — k3s Cluster Provisioning
Based on Architecture §10.1:

- Control plane: `k3s server --cluster-init`
- App worker node: `k3s agent` (join token)
- ML/GPU worker node: `k3s agent` with GPU device plugin
- Data node: `k3s agent` with node affinity labels for stateful services

Network: Flannel (k3s default) for pod networking; Traefik as ingress controller (k3s default).

#### Step 4.2 — Kubernetes Manifests / Helm Charts
Directory: `infra/helm/`

Create Helm charts for each service group:

| Chart | Services |
|---|---|
| `stock-analyst-app` | FastAPI, Next.js, Celery workers, Celery Beat, Flower |
| `stock-analyst-data` | PostgreSQL (with PVC), Qdrant (with PVC), MinIO (with PVC), Redis (with PVC) |
| `stock-analyst-ml` | Ollama, embedding job, reranker service |
| `stock-analyst-infra` | Keycloak, LiteLLM, Traefik (built-in but configured), Cert-Manager |
| `stock-analyst-obs` | Prometheus, Grafana, Loki, Sentry, Uptime Kuma |
| `stock-analyst-vault` | HashiCorp Vault with CSI driver |

All charts must support `values.yaml` override for site-specific configuration.

#### Step 4.3 — Persistent Volume Setup
- Data node PVCs: PostgreSQL (1TB), Qdrant (500GB), MinIO (10TB), Redis (50GB)
- Storage class: `local-path` on data node (k3s built-in) for MVP; document NFS migration path
- PVC retention policy: `Retain` (never auto-delete on PVC deletion)

#### Step 4.4 — Traefik Ingress & TLS
- TLS certificate: Cert-Manager with internal CA (on-premise, no Let's Encrypt dependency)
- Routes: `api.stock-analyst.internal`, `app.stock-analyst.internal`, `auth.stock-analyst.internal`
- Middleware: rate limiting (FastAPI already has it; Traefik adds a second layer), IP allowlist for admin routes

### Week 19 — Vault, Backup & Security Audit

#### Step 4.5 — HashiCorp Vault Integration
- Deploy Vault in HA mode (3 replicas on data node)
- Enable KV secrets engine: store LLM API keys, Keycloak client secrets, MinIO credentials
- Vault Agent Injector: inject secrets into pods as environment variables via annotations
- Rotate LLM API keys: Vault dynamic secrets or manual rotation workflow documented

**Acceptance:** Remove all secrets from Helm values.yaml; all pods get secrets via Vault injection; `vault lease renew` test passes

#### Step 4.6 — Velero Backup Configuration
File: `infra/helm/stock-analyst-backup/`

- Velero deployed with MinIO as backup storage (separate MinIO instance or bucket)
- Schedule: daily at 2am, retain 30 days
- Scope: all namespaces, all PVCs
- Include `restic` for volume-level backup (Qdrant and MinIO data)

**Test:** Full disaster recovery drill:
1. Snapshot cluster
2. Destroy all PVCs
3. Restore from Velero
4. Verify data integrity: count documents, query Qdrant, check PostgreSQL row counts

#### Step 4.7 — Security Audit
Scope: OWASP Top 10 + tenant isolation penetration test

Checklist:

- [ ] **A01 Broken Access Control** — attempt cross-tenant reads at API, DB, and Qdrant level; verify all blocked
- [ ] **A02 Cryptographic Failures** — TLS 1.3 enforced; no plaintext secrets in configs, logs, or env vars
- [ ] **A03 Injection** — SQL injection via coverage search endpoints (Pydantic validation + parameterized queries)
- [ ] **A04 Insecure Design** — audit log cannot be modified or deleted; verify append-only constraint
- [ ] **A05 Security Misconfiguration** — default Keycloak admin password changed; MinIO public access disabled; no open ports except 443
- [ ] **A06 Vulnerable Components** — `pip audit` + `npm audit` pass with no high/critical CVEs
- [ ] **A07 Authentication Failures** — verify JWT expiry enforced; no session fixation; test Keycloak token refresh
- [ ] **A08 Software Integrity** — Gitea Actions pipeline uses pinned action versions; container images from known registries only
- [ ] **A09 Logging Failures** — verify all agent calls logged; verify security events (auth failures, access denials) logged to Loki
- [ ] **A10 SSRF** — SEC EDGAR URL fetcher only allows edgar.sec.gov domain; `fetch_url` tool has allowlist

**Tenant isolation penetration test:** Using two separate test tenants (Tenant A and Tenant B), attempt:
- API: JWT from Tenant A used to access Tenant B's coverage endpoints → 403
- DB: Direct SQL with Tenant A's tenant_id → RLS blocks Tenant B's rows
- Qdrant: Query Tenant A's collection with Tenant B's coverage_id filter → zero results
- MinIO: Use Tenant A's pre-signed URL to access Tenant B's bucket → 403

### Week 20 — Load Testing, DR Runbook & Documentation

#### Step 4.8 — Load Testing
Tool: `Locust`

Scenarios:
1. **10 concurrent Lynch Pitch tasks** — all agents simultaneously generating bull cases for different coverages
2. **Ingestion stress test** — 5 concurrent 100-page PDF ingestions
3. **High-frequency RAG** — 50 concurrent RAG searches across all coverages
4. **Mixed workload** — realistic analyst session (view coverage, run task, poll status, view output) × 10 users

Success criteria: All NFR-PERF targets met under load; no errors; no cross-tenant data leakage detected in any log

#### Step 4.9 — Disaster Recovery Runbook
File: `docs/disaster-recovery.md`

Document procedures for:
1. **Single pod failure** — k3s restarts automatically; no action needed
2. **Node failure (app worker)** — reschedule pods to remaining nodes; re-add node
3. **Database corruption (PostgreSQL)** — restore from Velero backup; replay WAL if available
4. **Full cluster loss** — provision new k3s cluster; restore from Velero + restic; estimated RTO: 4 hours
5. **LLM API key compromise** — rotate in Vault; pods pick up new secret without restart
6. **Qdrant vector store corruption** — restore from backup; re-index documents from MinIO raw files (ingestion pipeline re-run)

Each procedure: step-by-step commands, expected output, verification steps.

#### Step 4.10 — Operator Documentation
Directory: `docs/`

- `installation-guide.md` — from bare metal to running system in <4 hours
- `upgrade-guide.md` — rolling upgrade procedure for each component
- `admin-guide.md` — user management, tenant setup, cost monitoring
- `troubleshooting.md` — common failure modes and resolution steps
- `api-reference.md` — auto-generated from FastAPI OpenAPI spec

---

## Test Plans

### TP.1 Unit Tests

**Target:** Every isolated function with deterministic behavior. Run in CI on every push. No external services needed (all dependencies mocked).

| Module | Test File | Key Cases |
|---|---|---|
| Financial Normalizer | `test_financial_normalizer.py` | 25+ format variations; edge cases: negative values, N/A, ranges |
| Hierarchical Chunker | `test_chunker.py` | Parent-child links preserved; metadata on every chunk; correct section assignment |
| Citation Enforcer | `test_citation_enforcer.py` | Pass on clean output; fail on each of 6 checks individually; retry_prompt contains correct instructions |
| Orchestrator Routing | `test_orchestrator_routing.py` | Each intent → correct agent; PREREQUISITE_MISSING for missing filings; PREREQUISITE_MISSING for missing industry |
| KPI Normalizer | `test_kpi_normalizer.py` | All standard financial KPI formats; restatement detection; definition change detection |
| Hybrid Retriever (mocked Qdrant) | `test_retriever.py` | Tenant filter always applied; coverage filter always applied; parent hydration works |
| RLS Middleware | `test_tenant_middleware.py` | SET LOCAL executed on every request; correct tenant_id extracted from JWT |

**Coverage target: ≥80% line coverage** on all `packages/` modules.

### TP.2 Integration Tests

**Target:** Components interacting with real backing services (PostgreSQL, Qdrant, MinIO, Redis). Run in CI against `docker compose` stack. Slower; run on PR, not every push.

| Test Suite | Services Used | Key Scenarios |
|---|---|---|
| `test_ingestion_integration.py` | PostgreSQL, Qdrant, MinIO, Ollama | Ingest real 10-K; verify chunks in Qdrant; verify document in DB; verify file in MinIO |
| `test_retrieval_integration.py` | Qdrant | Dense + sparse + reranker pipeline; zero cross-tenant results; parent hydration |
| `test_rls_integration.py` | PostgreSQL | Tenant A JWT cannot read Tenant B rows in any table |
| `test_auth_integration.py` | Keycloak | Valid JWT → 200; expired JWT → 401; wrong role → 403; cross-tenant JWT → 403 |
| `test_celery_integration.py` | Redis, Celery | Ingestion task enqueued; picked up; status transitions; error retry |
| `test_minio_integration.py` | MinIO | Pre-signed URL works; cross-tenant URL blocked; TTL expiry |

### TP.3 Agent Evaluation Tests

**Target:** Validate agent output quality using the golden evaluation dataset. Run manually before each phase gate and after any prompt changes.

#### TP.3.1 Industry Analyst Agent Evaluation
- Input: Industry name + 3 uploaded research documents
- Expected: All 6 sections present, all 5 bullets present, every claim cited, Citation Enforcer approves
- Failure modes to test: providing no documents (should gracefully fall back to web-only), web search returning irrelevant results

#### TP.3.2 Lynch Pitch Agent Evaluation
Test matrix:

| Scenario | Expected Behavior |
|---|---|
| Company with 3+ years of filings | All 8 questions answered; ≥95% citation coverage |
| Company with only 1 filing | Answers Q1-Q4 from available data; flags Q5-Q8 as "Not found" |
| Company with no revenue (pre-revenue) | Does not invent revenue; Q3 explicitly marked not found |
| Filing with scanned (image) content | Quality warning present; citations limited to extractable sections |
| Hallucination attempt: ask about metric not in filing | "Not found in uploaded documents" for that specific metric |

#### TP.3.3 Munger Invert Agent Evaluation
- Must identify at least one structural weakness when filings contain risk factors
- Must use footnotes section when footnotes discuss contingent liabilities
- Must not speculate about macro factors not mentioned in filings
- Management narrative vs data divergence: test with a company where stated guidance was missed

#### TP.3.4 Earnings Monitor Agent Evaluation
- Input: Prior 10-Q with guidance + new 10-Q with results
- Expected: Each prior guidance item matched to an actual result with exact dual citations
- Credibility verdict: manually verify against known outcomes for test company
- Recurring excuse detection: test with same management phrase in 3 consecutive quarters

#### TP.3.5 Citation Enforcer Regression Suite
Run after every change to Citation Enforcer:

- 10 known-good outputs → all must pass
- 10 known-bad outputs (hallucinations, missing citations, wrong format) → all must fail
- 5 borderline outputs (94% citation coverage, single format error) → validate enforcer catches these
- Verify retry prompt is actionable: manually give retry prompt back to a test LLM call and verify it fixes the issue

### TP.4 Performance Tests

**Target:** Validate NFR-PERF targets under realistic load.

| Test | Tool | Target | Measurement Point |
|---|---|---|---|
| Single 10-K ingestion latency | `time` + custom timer | <120s | task `created_at` → `completed_at` in DB |
| RAG retrieval latency (p95) | Locust | <500ms | Qdrant query + reranker response time |
| Lynch Pitch e2e latency | Locust | <90s | WebSocket `complete` event timestamp − task `created_at` |
| Quarterly Update e2e latency | Locust | <120s | Same as above |
| 10 concurrent Lynch Pitch tasks | Locust | All <90s | All tasks complete within target; no errors |
| 5 concurrent ingestion tasks | Locust | All <120s | Verify no Qdrant write conflicts |
| 50 concurrent RAG queries | Locust | p95 <500ms | Verify Qdrant handles concurrent reads |

### TP.5 Security Tests

**Target:** Validate tenant isolation and OWASP top 10 controls.

| Test | Method | Pass Condition |
|---|---|---|
| Cross-tenant API access | Use Tenant A JWT on Tenant B `/coverages/{id}` | HTTP 403 |
| Cross-tenant DB access | Direct SQL with wrong tenant_id | Zero rows returned (RLS) |
| Cross-tenant Qdrant access | Query Tenant A collection with Tenant B coverage_id | Zero results |
| Cross-tenant MinIO access | Tenant A pre-signed URL on Tenant B bucket | HTTP 403 |
| SQL injection via search | `'; DROP TABLE coverages; --` in search query | Query fails gracefully; table intact |
| JWT expiry | Use an expired JWT | HTTP 401 |
| JWT tampering | Modify payload, keep signature | HTTP 401 |
| Unauthorized agent trigger | Viewer role triggers Lynch Pitch | HTTP 403 |
| Output approval by analyst | Analyst role tries to approve output | HTTP 403 |
| Audit log immutability | DELETE from `agent_audit_log` | Permission denied (Postgres GRANT) |
| SSRF via fetch_url tool | `fetch_url("http://internal-service/admin")` | Rejected; allowlist enforced |

### TP.6 End-to-End (E2E) Tests

**Target:** Full user journeys through the system. Run manually pre-release and via Playwright in CI weekly.

#### E2E-01: New Coverage Onboarding
1. Admin creates a new tenant and analyst user
2. Analyst logs in, creates a new coverage for "MSFT"
3. System auto-fetches 3 years of 10-K filings from SEC EDGAR
4. Ingestion completes; document list shows 3 indexed documents
5. Analyst runs Industry Analysis for "Enterprise Software"
6. Industry primer appears with all 6 sections and citations

**Pass:** All steps complete without manual intervention; no errors in logs

#### E2E-02: Full Research Workflow (Bull/Bear)
1. (Assuming E2E-01 complete)
2. Analyst runs Lynch Pitch → streams via WebSocket → output appears with citations
3. Analyst clicks a citation → document opens at correct page
4. Analyst runs Munger Invert → output appears
5. Senior analyst reviews and approves both outputs
6. Analyst exports PDF report → PDF contains both outputs with footnotes

**Pass:** No Citation Enforcer failures; PDF renders correctly

#### E2E-03: Quarterly Earnings Update
1. (Assuming active coverage with prior quarters)
2. New 10-Q is uploaded (or auto-detected)
3. Earnings Monitor runs automatically
4. Analyst receives in-app notification
5. Quarterly update page shows guidance vs reality table
6. KPI dashboard shows new data point on time-series chart

**Pass:** Prior guidance matched correctly; KPI time-series updated; notification delivered

#### E2E-04: Multi-Tenant Isolation
1. Tenant A analyst creates a coverage for "AAPL" and uploads documents
2. Tenant B analyst logs in
3. Tenant B cannot see Tenant A's coverages in their list
4. Direct URL attempt to Tenant A's coverage returns 403
5. Tenant B creates their own coverage for "AAPL" (separate isolated project)
6. Both tenants' data remains fully separate

**Pass:** Zero cross-tenant data visible; no 500 errors

---

## Deployment Plan

### DP.1 Deployment Environments

| Environment | Infrastructure | Purpose | Data |
|---|---|---|---|
| **Local Dev** | Docker Compose (single machine) | Development; rapid iteration | Synthetic/test data |
| **Integration** | Docker Compose (CI server) | Automated tests; PR validation | Test fixtures; real SEC filings (small set) |
| **Staging** | k3s (1 control + 1 worker node) | Pre-production validation; UAT with real analysts | Production-like data; test tenants |
| **Production** | k3s (4-node cluster, Architecture §10.1) | Live analyst use | Real company filings |

### DP.2 Local Development Setup

**Prerequisites:** Docker Desktop, `kubectl`, `helm`, `python 3.12`, `node 20`, `k9s` (optional)

```bash
# 1. Clone and configure
git clone http://gitea.internal/stock-analyst/stock-analyst.git
cd stock-analyst
cp .env.example .env
# Edit .env: add ANTHROPIC_API_KEY, OPENAI_API_KEY

# 2. Start all services
docker compose up -d --wait

# 3. Run migrations
docker compose exec api alembic upgrade head

# 4. Seed test data
docker compose exec api python scripts/seed_dev.py

# 5. Pull embedding model
docker compose exec ollama ollama pull nomic-embed-text:v1.5

# 6. Start frontend dev server
cd apps/web && npm install && npm run dev
```

**Verification:** Open `http://localhost:3000` → login as `analyst@tenant-a.test` / `TestPass123`

### DP.3 Staging Deployment

**Steps:**
1. Build container images: `docker build` for each service; push to Gitea container registry
2. Configure `values.staging.yaml` overriding dev defaults (2 CPU, 4GB RAM per pod for staging)
3. Deploy: `helm upgrade --install stock-analyst-app infra/helm/stock-analyst-app -f values.staging.yaml`
4. Run migration job: `kubectl create job --from=cronjob/db-migrate migrate-$(date +%s)`
5. Verify health: `kubectl get pods -n stock-analyst` — all pods Running; `curl https://api.staging.internal/health/deep` — all services healthy
6. Run integration test suite against staging: `pytest tests/integration/ --env=staging`
7. UAT: real analyst runs through E2E-01 and E2E-02 manually

### DP.4 Production Deployment

#### DP.4.1 Pre-Deployment Checklist
- [ ] All CI checks pass on the release branch
- [ ] Evaluation test suite passes (≥95% citation coverage on golden eval set)
- [ ] Security audit completed; all High/Critical findings resolved
- [ ] Load test passed (10 concurrent analysts within latency targets)
- [ ] Disaster recovery drill completed; RTO documented
- [ ] Backup policy configured and tested (Velero)
- [ ] Vault secrets configured for production LLM API keys
- [ ] DNS entries configured for production domains
- [ ] TLS certificates issued by internal CA
- [ ] Operator runbook handed to IT team; dry-run performed

#### DP.4.2 First-Time Cluster Bootstrap
```bash
# Control plane
curl -sfL https://get.k3s.io | K3S_TOKEN=<secret> sh -s - server --cluster-init

# App worker
curl -sfL https://get.k3s.io | K3S_TOKEN=<secret> K3S_URL=https://<control-plane>:6443 sh -

# ML/GPU worker (same command + GPU device plugin afterwards)
# Data node (same command + node label for affinity)
kubectl label node <data-node> node-role.kubernetes.io/data=true

# Create namespaces
kubectl apply -f infra/k8s/namespaces/

# Install Vault first (other services depend on secrets)
helm upgrade --install vault infra/helm/stock-analyst-vault -n stock-analyst-infra

# Initialize and unseal Vault (manual step; document key shares)
# Configure Vault AppRoles, KV secrets, CSI driver

# Deploy remaining services in order
helm upgrade --install data infra/helm/stock-analyst-data -n stock-analyst-data
helm upgrade --install ml   infra/helm/stock-analyst-ml   -n stock-analyst-ml
helm upgrade --install app  infra/helm/stock-analyst-app  -n stock-analyst

# Run DB migration
kubectl create job --from=cronjob/db-migrate initial-migrate -n stock-analyst

# Deploy observability stack
helm upgrade --install obs infra/helm/stock-analyst-obs -n stock-analyst-obs
```

#### DP.4.3 Rolling Upgrades (Subsequent Releases)
1. Build and push new container images (tagged with git SHA)
2. Update image tags in `values.production.yaml`
3. Run: `helm upgrade stock-analyst-app infra/helm/stock-analyst-app -n stock-analyst`
4. k8s performs rolling update (zero-downtime for stateless services)
5. If DB migration required: run migration job before upgrading app pods
6. Monitor in Grafana: error rate, latency, pod restart count during rollout
7. Rollback if needed: `helm rollback stock-analyst-app` (reverts to previous Helm revision)

#### DP.4.4 Monitoring & Alerting Setup
Configure Prometheus AlertManager rules for production:

| Alert | Condition | Severity | Response |
|---|---|---|---|
| `CritationEnforcerHighRetryRate` | avg retries > 2.0 over 10m | Warning | Review recent agent outputs; check prompt changes |
| `IngestionPipelineSlow` | p95 ingestion > 180s | Warning | Check Ollama GPU utilization; check Docling queue |
| `HallucinationRateHigh` | hallucination_rate > 1% | Critical | Alert on-call; disable agent output approval until resolved |
| `CrossTenantAccessAttempt` | any 403 from RLS or Qdrant filter mismatch | Critical | Immediate investigation; audit log review |
| `LLMCostSpike` | tenant monthly cost > 1.5× previous month | Warning | Alert tenant admin; check for runaway scheduled tasks |
| `QdrantHighLatency` | p95 query > 800ms | Warning | Check index health; consider collection compaction |
| `PostgreSQLDiskHigh` | data node disk > 80% | Warning | Review and archive old audit logs; expand volume |
| `BackupFailure` | Velero schedule missed | Critical | Immediately trigger manual backup; investigate |

### DP.5 Post-Deployment Verification

After every production deployment:

```
1. GET /health/deep → all services 200
2. Login as test analyst → auth works
3. Load existing coverage → documents visible
4. Run a KPI query → retrieval works, latency <500ms
5. Check Grafana dashboard → no elevated error rates
6. Check LangSmith → traces appearing for test query
7. Check Loki logs → no unexpected errors in last 15 minutes
```

If any step fails: roll back immediately using `helm rollback`; investigate before re-deploying.

---

## Risk Register

### Development Risks

| Risk | Phase | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| nomic-embed model slow on CPU (no GPU during dev) | Phase 1 | High | Medium | Use smaller batch sizes during dev; full GPU in staging |
| Docling table extraction inaccurate for complex financial tables | Phase 1 | Medium | High | Build fallback: if Docling confidence <0.7, store raw markdown; flag for review |
| LangGraph state persistence complexity | Phase 2 | Medium | High | Start with in-memory checkpointer; add PostgreSQL checkpointer only in Phase 3 |
| Tavily API rate limits during Industry Agent development | Phase 2 | Medium | Low | Cache Tavily results in Redis for dev; use mock responses in unit tests |
| Citation Enforcer too strict → agents never pass → development blocked | Phase 2 | Medium | High | Start enforcer at 80% threshold; tighten to 95% in Phase 3 once prompts are tuned |
| GPT-4o JSON output mode inconsistency for KPI extraction | Phase 2 | Medium | Medium | Use structured output (response_format=json_schema); add Pydantic validation with retry |

### Infrastructure Risks

| Risk | Phase | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| Qdrant performance degrades with large collection size | Phase 4 | Low | High | Test with 10M vectors in staging; configure HNSW index params; plan collection sharding |
| MinIO disk space: 10TB fills up with many coverages | Phase 4 | Medium | Medium | Implement document lifecycle policy: archive filings older than 5 years to cold storage |
| k3s etcd instability (single control plane) | Phase 4 | Low | Critical | Document HA control plane option for enterprise deployments; take daily etcd snapshots |
| GPU worker node unavailable for Ollama | Phase 4 | Low | Medium | Primary LLMs (Claude, GPT-4o) unaffected; embedding uses GPU but can fall back to CPU (slower) |

---

## Build Order Summary

| Phase | Duration | Deliverable | Gate Criteria |
|---|---|---|---|
| R (Requirements) | Pre-Week 1 | This document | Stakeholder sign-off |
| D (Design) | Pre-Week 1 | Interface contracts agreed | Team alignment session |
| 0 (Foundation) | Weeks 1–3 | Authenticated multi-tenant shell | All Docker Compose services healthy; auth works; RLS integration test passes |
| 1 (Document Backbone) | Weeks 4–7 | End-to-end ingestion + retrieval | 100-page 10-K ingested in <120s; retrieval p95 <500ms; cross-tenant zero results |
| 2 (Core Agents) | Weeks 8–13 | All 7 agents live with Citation Enforcer | 5-step workflow completes for a real stock; ≥95% citation coverage on eval set |
| 3 (Quality/UX) | Weeks 14–17 | Production-quality UX + streaming + exports | Streaming works; PDF export works; load test (10 analysts) passes; eval suite ≥95% |
| 4 (Production Hardening) | Weeks 18–20 | k3s cluster + security audit + DR runbook | Security audit no Critical/High findings; DR drill RTO <4h; Velero backup tested |
| **Total** | **~20 weeks** | **Production-ready on-premise platform** | — |

---

*Development Plan v1.0 — Stock Analyst AI Platform*  
*Based on Architecture v1.0 · Self-hosted · Multi-tenant · Quote-first · Source-disciplined*
