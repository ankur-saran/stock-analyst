# Stock Analyst AI

A self-hosted, multi-tenant agentic platform that automates the 5-step equity
research workflow (industry primer → document ingestion → bull case → bear
case → quarterly monitoring) for professional equity analysts. Every agent
output is quote-first and source-disciplined: no factual claim may reach a
user without a citation that resolves to an exact passage in an ingested
document, enforced by a dedicated validation gate rather than by prompting
alone.

## Contents

- [How it works](#how-it-works)
- [Agents](#agents)
- [Architecture](#architecture)
- [Tech stack](#tech-stack)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [API surface](#api-surface)
- [Testing](#testing)
- [CI/CD](#cicd)
- [Multi-tenancy & security](#multi-tenancy--security)
- [Further documentation](#further-documentation)

## How it works

Each stock a firm researches is a **Coverage** (ticker + exchange), scoped to
a **Tenant** (the analyst's organization). A coverage moves through:

1. **Industry Analyst** — produces a one-time, reusable industry primer per
   industry (web research + uploaded documents).
2. **Document Ingestion** — fetches SEC filings (10-K/10-Q/8-K) or accepts
   uploads, parses, extracts tables, normalizes financials, chunks, embeds,
   and indexes everything with page/section-level metadata.
3. **Lynch Pitch** (bull case) — answers 8 fixed questions ("why own this
   stock?") using only that coverage's indexed documents.
4. **Munger Invert** (bear case) — adversarial inversion of the same
   evidence, built to invalidate the thesis rather than balance it.
5. **Earnings Monitor + KPI Tracker** — on each new filing, compares prior
   guidance to actual results quote-for-quote, tracks a management
   credibility score, and maintains a per-industry KPI time series.

A **Citation Enforcer** validates every agent output before it's stored or
shown to a user: it checks citation coverage (≥95% of claims cited), citation
format, that every quoted string actually exists in the vector store
(hallucination check), that figures aren't left unsourced, and that
speculative language is flagged as inference rather than stated as fact.
Outputs that fail are sent back to the originating agent (up to 3 retries)
or surfaced with a `PARTIAL — manual review required` flag.

## Agents

| Agent | Role | Package |
|---|---|---|
| Orchestrator | Routes user intent to the right agent; runs prerequisite checks (industry loaded? enough filings?) before allowing research tasks | `packages/agents/src/agents/orchestrator` |
| Industry Analyst | 6-section industry primer + 5-bullet investor synthesis, reused across all coverages in that industry | `packages/agents/src/agents/industry_analyst` |
| Lynch Pitch | 8-question bull case, refuses to answer unsupported claims | `packages/agents/src/agents/lynch_pitch` |
| Munger Invert | 8-question adversarial bear case; searches footnotes and off-balance-sheet items | `packages/agents/src/agents/munger_invert` |
| Earnings Monitor | Guidance-vs-reality tracking with dual (prior + current) citations; management credibility scoring | `packages/agents/src/agents/earnings_monitor` |
| KPI Tracker | Auto-detects industry-relevant KPIs, extracts and normalizes a time series with restatement detection | `packages/agents/src/agents/kpi_tracker` |
| Citation Enforcer | Shared validation gate all agent output passes through | `packages/agents/src/agents/shared/citation_enforcer.py` |

Industry → KPI vocabulary is configured in [`infra/kpi_definitions.yaml`](infra/kpi_definitions.yaml)
(enterprise software, SaaS, retail, regional banking, semiconductors,
manufacturing, plus a default financial-statement set for any other industry).

## Architecture

```
Next.js 14 web app  ──HTTPS/WSS──>  FastAPI (JWT auth via Keycloak, tenant middleware)
                                            │
                     ┌──────────────┬───────┴────────┬────────────────┐
                 coverages      documents          tasks            outputs/kpis/notes/search
                                            │
                              LangGraph Orchestrator + Citation Enforcer
                                            │
             ┌───────────────┬─────────────┼─────────────┬───────────────────┐
       Industry Analyst  Doc Ingestion  Lynch Pitch  Munger Invert   Earnings Monitor / KPI Tracker
                                            │
                    Hybrid Retriever (Qdrant dense + sparse, RRF fusion, CrossEncoder rerank)
                                            │
                     PostgreSQL (RLS)   Qdrant (per-tenant collections)   MinIO (per-tenant buckets)
```

Tenant isolation is enforced at three layers simultaneously: PostgreSQL
Row-Level Security (`SET LOCAL app.current_tenant_id`, applied by
`apps/api/middleware/tenant.py` on every request), a dedicated Qdrant
collection per tenant, and a dedicated MinIO bucket per tenant.

Background work (document ingestion, agent task dispatch, the daily new-filing
sweep) runs on Celery, broker'd through Redis; Celery Beat only *enqueues*
the daily sweep and must run as a single replica separate from the workers
that execute it (see `infra/docker-compose.yml`).

## Tech stack

| Layer | Technology |
|---|---|
| LLM routing | LiteLLM proxy → Anthropic Claude (primary), OpenAI GPT-4o (secondary), Llama 3.1 via Ollama (local/air-gapped fallback) |
| Agent orchestration | LangGraph state graph, Celery + Redis for async/scheduled work |
| RAG | Qdrant (dense + sparse hybrid), CrossEncoder reranker, `nomic-embed-text-v1.5` embeddings via Ollama |
| Document processing | PyMuPDF, Docling-style table extraction, custom financial normalizer, SEC EDGAR connector |
| Backend | FastAPI, SQLAlchemy (async) + PostgreSQL 16, Pydantic v2, structlog |
| Auth | Keycloak (OIDC/OAuth2, RBAC: viewer / analyst / senior_analyst / admin) |
| Frontend | Next.js 14 (App Router), NextAuth (Keycloak provider), shadcn/ui + Radix, TailwindCSS, TanStack Query, Zustand, Recharts, Tiptap |
| Storage | PostgreSQL, MinIO (S3-compatible), Redis |
| Infra | Docker Compose (local dev), k3s + Helm (production), Traefik, HashiCorp Vault, Velero/restic backups |
| CI | Gitea Actions — lint, unit tests, migration tests, integration tests (manual trigger), agent quality eval gate (on merge to `main`) |

## Repository layout

```
apps/
  api/            FastAPI backend — routers, middleware, Celery tasks, services (storage, streaming, PDF export, notifications)
  web/            Next.js 14 frontend — coverages, research views, KPI dashboard, admin/usage
packages/
  agents/         LangGraph agent implementations, prompts, schemas, tools (one subpackage per agent)
  rag/            Ingestion pipeline (parsers, chunkers), hybrid retriever, connectors (SEC EDGAR, Qdrant)
  shared/         Shared Pydantic models, settings, streaming utilities
infra/
  docker-compose.yml   Local dev stack (Postgres, Redis, Qdrant, MinIO, Keycloak, Ollama, LiteLLM, API, Celery)
  helm/                Production Helm charts (app / data / ml / infra / obs)
  k8s/                 Namespaces, backup, Vault manifests
  keycloak/            Realm export (roles, clients, test users)
  litellm/             LLM gateway routing config
  kpi_definitions.yaml Industry → KPI vocabulary
migrations/       Alembic migrations
eval/             Golden evaluation datasets + runner (per-agent citation/hallucination quality gate)
tests/            unit / integration / e2e / load test suites
scripts/          seed_dev.py, setup_minio.py, reindex_all.py
docs/             Disaster recovery runbook
```

## Getting started

**Prerequisites:** Docker with the Compose plugin, Python ≥3.12, Node ≥20.
On Windows, use Git Bash or WSL for the `Makefile` targets (PowerShell users
need to set `PYTHONPATH` manually for the `dev-api`/Celery targets).

```bash
# 1. Configure environment
cp .env.example .env        # then fill in ANTHROPIC_API_KEY, OPENAI_API_KEY, etc.

# 2. Start backing services (Postgres, Redis, Qdrant, MinIO, Keycloak, Ollama, LiteLLM)
make up

# 3. Apply database migrations
make migrate

# 4. Seed dev data (2 tenants, 4 roles, 3 industries) and MinIO buckets
make seed

# 5. Pull the local embedding model
make pull-model

# 6. Run the API and worker (separate terminals)
make dev-api          # FastAPI on http://localhost:8000 (docs at /docs)
make celery-worker
make celery-beat      # optional locally — only needed to test the daily filing sweep

# 7. Run the frontend
cp apps/web/.env.local.example apps/web/.env.local   # if present; otherwise create it — see below
npm install
make dev-web          # Next.js on http://localhost:3000
```

`apps/web` needs its own `.env.local` (not covered by the root `.env.example`)
with at least:

```
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_KEYCLOAK_URL=http://localhost:8080
NEXT_PUBLIC_KEYCLOAK_CLIENT_ID=stock-analyst-web
NEXTAUTH_URL=http://localhost:3000
NEXTAUTH_SECRET=<generate with: openssl rand -hex 32>
```

Default local ports: API `8000`, web `3000`, Postgres `5432`, Redis `6379`,
Qdrant `6333`/`6334`, MinIO `9000`/`9001` (console), Keycloak `8080`, Ollama
`11434`, LiteLLM `4000`.

Alternatively, `Dockerfile.api` builds the API/Celery image directly if you
want to run everything (app included) through `infra/docker-compose.yml`.

## API surface

All routes are served without a version prefix (e.g. `http://localhost:8000/coverages`).
Interactive docs are at `/docs` outside production.

| Area | Routes |
|---|---|
| Health | `GET /health`, `GET /health/deep` |
| Coverages | `POST /coverages`, `GET /coverages`, `GET/DELETE /coverages/{id}`, `GET /coverages/{id}/kpis[/{kpi_name}]` |
| Documents | `POST /coverages/{id}/documents`, `GET /coverages/{id}/documents`, `GET .../{document_id}/presigned-url`, `POST .../{document_id}/retry`, `DELETE .../{document_id}` |
| Agent tasks | `POST /coverages/{id}/tasks/industry-analysis`, `POST /coverages/{id}/tasks/{agent_name}`, `POST /coverages/{id}/orchestrate`, `GET/DELETE /tasks/{task_id}`, `WS /ws/tasks/{task_id}` (streamed progress/citation/complete events) |
| Research outputs | `GET /coverages/{id}/outputs[/{output_id}]`, `POST /coverages/{id}/outputs/{output_id}` (approve), `GET /coverages/{id}/report.pdf` |
| Notes & search | `GET/POST /coverages/{id}/notes`, `GET /coverages/{id}/search` |
| Industries | `GET /industries[/{id}]` |
| Notifications | `GET /notifications/unread`, `POST /notifications/{id}/read` |
| Admin | `GET /admin/tenants`, `GET /admin/usage`, `PUT /admin/tenants/{id}/alert-threshold`, `GET /admin/agents/health` |

## Testing

```bash
make test                                  # unit tests, ≥80% coverage gate on apps/api/services
pytest tests/unit/                         # same, without the coverage gate
pytest tests/integration/ -m integration   # requires the docker compose stack running
pytest tests/e2e/                          # end-to-end analyst workflow
locust -f tests/load/locustfile.py         # load testing
python -m eval.runners.run_eval --agent lynch_pitch --env dev --output-html eval/reports/
```

Lint/type-check: `make lint` (ruff + ruff format + mypy `--strict` on
`packages/` and `apps/api/`), plus `npm run lint` / `tsc --noEmit` for the
frontend.

## CI/CD

`.gitea/workflows/ci.yml` runs on every push/PR: Python lint, frontend lint,
unit tests (coverage-gated), and a migration round-trip test
(`upgrade head` → `downgrade base` → `upgrade head`). Two heavier jobs are
gated further: an infrastructure smoke test (manual trigger only) and an
**eval gate** that runs on every push to `main` — it stands up the full
Compose stack, runs the golden evaluation set for all five research agents,
and fails the build if pass rate < 100%, average citation coverage < 95%, or
hallucination rate > 0.5% for any agent.

## Multi-tenancy & security

- **Isolation:** PostgreSQL RLS + per-tenant Qdrant collection + per-tenant
  MinIO bucket, enforced independently at each layer.
- **RBAC:** `viewer` / `analyst` / `senior_analyst` / `admin`, defined in the
  Keycloak realm (`infra/keycloak/realm-export.json`) and read from the JWT.
- **Auditability:** every agent call and document access writes to an
  append-only audit log.
- **Air-gapped mode:** the local Llama fallback (via Ollama/LiteLLM) allows
  operation with zero external LLM calls when required.
- See `infra/scripts/security_audit.sh` for the OWASP-Top-10-style audit
  checklist used before production deployment.

## Further documentation

- [`Stock_Analyst_AI_Architecture.md`](Stock_Analyst_AI_Architecture.md) — full architecture spec (agent prompts/tools, data models, RAG pipeline, deployment topology)
- [`Stock_Analyst_Development_Plan.md`](Stock_Analyst_Development_Plan.md) — phased build plan, requirements traceability, test plans, risk register
- [`docs/disaster-recovery.md`](docs/disaster-recovery.md) — DR runbook (pod/node failure, DB restore, full cluster loss, key rotation)
- [`Agentic_Dev_Prompts_Index.md`](Agentic_Dev_Prompts_Index.md) and the accompanying `Agentic_Dev_Prompts_*.md` files — the phase-by-phase prompts used to build this system
