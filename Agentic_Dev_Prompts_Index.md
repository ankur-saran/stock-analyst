# Stock Analyst AI — Agentic Development Prompts: Index & Usage Guide

## How to Use These Prompts

Each prompt is a self-contained task specification ready to paste into Claude Code (`claude`) or any agentic coding tool. Prompts within a phase must run in the numbered order shown — each builds on outputs from the previous.

**Files:**
- [Agentic_Dev_Prompts_Phase0_Phase1.md](Agentic_Dev_Prompts_Phase0_Phase1.md) — Infrastructure + Document backbone
- [Agentic_Dev_Prompts_Phase2_Agents.md](Agentic_Dev_Prompts_Phase2_Agents.md) — All 7 AI agents
- [Agentic_Dev_Prompts_Phase3_Phase4_Tests.md](Agentic_Dev_Prompts_Phase3_Phase4_Tests.md) — Quality, deployment, test suite

---

## Prompt Inventory

### Phase 0 — Foundation Infrastructure (Weeks 1–3)

| Prompt | Title | Delivers | Hard Dependency |
|---|---|---|---|
| **0.1** | Monorepo Scaffold & Docker Compose | Full local stack running (PostgreSQL, Redis, Qdrant, MinIO, Keycloak, Ollama, LiteLLM) | None |
| **0.2** | Database Schema, Migrations & RLS | 9 tables with RLS policies; Alembic migrations; seed script | 0.1 |
| **0.3** | FastAPI Auth, Tenant Middleware & Health Endpoints | Authenticated API; JWT validation; tenant RLS activation; /health/deep | 0.2 |
| **0.4** | Keycloak Realm & Next.js Auth Shell | SSO login/logout; role-based nav; session with tenant_id | 0.3 |
| **0.5** | CI Pipeline & MinIO Bucket Policies | Gitea Actions CI; per-tenant buckets; StorageService with isolation | 0.4 |

### Phase 1 — Document Backbone (Weeks 4–7)

| Prompt | Title | Delivers | Hard Dependency |
|---|---|---|---|
| **1.1** | SEC EDGAR Connector & PDF Parser | Auto-fetch 10-K/Q/8-K from EDGAR; PyMuPDF + Unstructured fallback | 0.5 |
| **1.2** | Table Extractor & Financial Normalizer | Docling table extraction; 25+ numeric format normalizations | 1.1 |
| **1.3** | Hierarchical Chunker, Embedding Pipeline & BM25 | Parent/child chunks; nomic-embed-text; dense + sparse Qdrant vectors | 1.2 |
| **1.4** | Hybrid Retriever & Ingestion API | RRF + CrossEncoder reranker; Celery ingestion task; REST endpoints | 1.3 |
| **1.5** | Document Management UI | Document list with polling; upload modal; SEC auto-fetch UI | 1.4 |

### Phase 2 — Core Agents (Weeks 8–13)

| Prompt | Title | Delivers | Hard Dependency |
|---|---|---|---|
| **2.1** | Shared Agent Infrastructure | BaseAgent, AgentMessage, LangGraph state graph, Orchestrator tools | 1.4 |
| **2.2** | Citation Enforcer | All 6 validation checks; retry prompt builder; hallucination detection | 2.1 |
| **2.3** | Orchestrator Agent | Routing, prerequisite checks, task dispatch; /orchestrate endpoint | 2.2 |
| **2.4** | Industry Analyst Agent | Tavily web research; 6-section primer; extended thinking; SSRF protection | 2.3 |
| **2.5** | Lynch Pitch Agent (Bull Case) | 8-question bull case; parallel RAG; AnswerWithCitation schema | 2.4 |
| **2.6** | Munger Invert, KPI Tracker & Earnings Monitor | Adversarial bear case; KPI time-series; guidance vs results comparison | 2.5 |

### Phase 3 — Quality, UX & Intelligence (Weeks 14–17)

| Prompt | Title | Delivers | Hard Dependency |
|---|---|---|---|
| **3.1** | Evaluation Framework & Hallucination Detection | Golden eval datasets; eval runner; HTML report; semantic hallucination detection; CI eval gate | 2.6 |
| **3.2** | WebSocket Streaming & Research Output UI | Redis pub/sub streaming; WebSocket endpoint; bull/bear side-by-side UI; citation tooltips | 3.1 |
| **3.3** | PDF Export, Analyst Notes & Earnings Calendar | WeasyPrint PDF; Tiptap citation editor; Celery Beat auto-trigger; LLM cost dashboard | 3.2 |

### Phase 4 — Production Hardening (Weeks 18–20)

| Prompt | Title | Delivers | Hard Dependency |
|---|---|---|---|
| **4.1** | k3s Cluster Setup & Helm Charts | 5 namespaces; 5 Helm charts (data, app, ml, infra, obs); bootstrap script | 3.3 |
| **4.2** | Vault, Velero Backup & Security Audit | Vault CSI; daily Velero backup; security audit script; DR runbook | 4.1 |

### Test Suite

| Prompt | Title | Delivers | Hard Dependency |
|---|---|---|---|
| **TEST.1** | Comprehensive Test Suite Setup | conftest.py; full workflow integration test; cross-tenant isolation test; Playwright E2E; Locust load test | All phases |

---

## Execution Order (Linear Build Path)

```
0.1 → 0.2 → 0.3 → 0.4 → 0.5
                              ↓
                   1.1 → 1.2 → 1.3 → 1.4 → 1.5
                                               ↓
                              2.1 → 2.2 → 2.3 → 2.4 → 2.5 → 2.6
                                                                  ↓
                                              3.1 → 3.2 → 3.3
                                                              ↓
                                              4.1 → 4.2 → TEST.1
```

---

## Prompt Design Principles

Every prompt in this series follows these rules so agents can execute them reliably:

1. **Self-contained context** — Each prompt summarizes what already exists. The agent never needs to read prior prompts.
2. **Explicit file paths** — Every file to create or edit is named with its full relative path.
3. **Acceptance criteria at the end** — Numbered, testable criteria the agent can verify before finishing.
4. **Constraints section** — Security requirements, performance invariants, and design decisions the agent must not deviate from.
5. **No open-ended tasks** — Every deliverable is bounded. "Implement X" is always followed by the interface, schema, or test that defines done.

---

## Gate Criteria Per Phase (Do Not Proceed Without)

| Gate | Phase | Must Pass Before Starting Next Phase |
|---|---|---|
| **Gate 0** | After Phase 0 | `GET /health/deep` returns all services healthy; auth integration test passes; `alembic upgrade head` works |
| **Gate 1** | After Phase 1 | 100-page 10-K ingested in <120s; HybridRetriever p95 <500ms; zero cross-tenant results confirmed |
| **Gate 2** | After Phase 2 | Full 5-step workflow completes for a real stock; Citation Enforcer approves; ≥95% citation coverage on eval set |
| **Gate 3** | After Phase 3 | WebSocket streaming works; PDF export works; Locust load test (10 users) passes latency targets |
| **Gate 4** | After Phase 4 | Security audit script exits 0; Velero backup + restore tested; DR runbook dry-run completed |

---

## Tips for Agentic Execution

- **Give context on first use**: When starting a new Claude Code session for a prompt, also share the relevant architecture sections from `Stock_Analyst_AI_Architecture.md` that the prompt references.
- **Run acceptance criteria last**: After the agent completes, paste the acceptance criteria back in as a verification task: "Verify each of these criteria is met."
- **Broken dependency**: If a prompt fails because a prior prompt's output is incomplete, fix the prior output first — don't try to work around missing foundations.
- **Parallel candidates**: Prompts 2.4, 2.5, and 2.6 can be split across parallel agent sessions once 2.3 is done — they share the BaseAgent but don't depend on each other.
- **Test prompts**: TEST.1 can be partially run after each phase gate (unit tests after Phase 2; integration tests after Phase 3; E2E + load tests after Phase 4).
