# Stock Analyst AI — Agentic Development Prompts
## Phase 0 & Phase 1: Foundation + Document Backbone

Each prompt is self-contained and ready to paste directly into Claude Code or any agentic coding tool. Prompts within a phase must be run in the numbered order shown — each builds on the previous.

---

## PROMPT 0.1 — Monorepo Scaffold & Docker Compose Stack

```
You are implementing the foundation of a self-hosted, multi-tenant Stock Analyst AI platform.
Your task is to scaffold the monorepo and bring up the full local development stack.

PROJECT OVERVIEW:
A multi-tenant equity research platform where AI agents generate source-cited stock analysis.
Stack: FastAPI backend, Next.js 14 frontend, PostgreSQL, Qdrant, MinIO, Redis, Keycloak, Ollama, LiteLLM.

MONOREPO STRUCTURE TO CREATE:
stock-analyst/
├── apps/
│   ├── api/          # FastAPI backend (Python 3.12)
│   └── web/          # Next.js 14 frontend
├── packages/
│   ├── agents/       # LangGraph agent implementations
│   ├── rag/          # RAG pipeline (ingestion + retrieval)
│   └── shared/       # Shared Pydantic models, config
├── infra/
│   ├── docker-compose.yml
│   ├── keycloak/     # realm-export.json
│   ├── litellm/      # config.yaml
│   └── k8s/          # empty for now
├── eval/
│   ├── datasets/
│   ├── runners/
│   └── reports/
├── migrations/       # Alembic migrations
├── scripts/          # Admin/seed scripts
└── docs/

TASK 1 — Create docker-compose.yml at infra/docker-compose.yml:
Services (all with health checks and named volumes):
- postgres: image postgres:16, port 5432, env POSTGRES_DB=stockanalyst POSTGRES_USER=stockanalyst POSTGRES_PASSWORD from .env
- redis: image redis:7-alpine, port 6379, command: redis-server --appendonly yes
- qdrant: image qdrant/qdrant:latest, port 6333 + 6334, volume for /qdrant/storage
- minio: image minio/minio:latest, port 9000 + 9001 (console), command: server /data --console-address ":9001", env MINIO_ROOT_USER + MINIO_ROOT_PASSWORD from .env
- keycloak: image quay.io/keycloak/keycloak:24.0, port 8080, command: start-dev --import-realm, volume mount infra/keycloak/realm-export.json to /opt/keycloak/data/import/realm-export.json, env KEYCLOAK_ADMIN + KEYCLOAK_ADMIN_PASSWORD from .env
- ollama: image ollama/ollama:latest, port 11434, volume for /root/.ollama, runtime nvidia if GPU available
- litellm: image ghcr.io/berriai/litellm:main-latest, port 4000, volume mount infra/litellm/config.yaml, env ANTHROPIC_API_KEY + OPENAI_API_KEY from .env
All services on a named network "stockanalyst-net".

TASK 2 — Create infra/litellm/config.yaml:
model_list with three entries:
  - model_name: primary → anthropic/claude-sonnet-4-6 (use sonnet for dev cost control; ops can switch to opus-4-8)
  - model_name: secondary → openai/gpt-4o
  - model_name: local → ollama/llama3.1:70b at http://ollama:11434
router_settings:
  fallbacks: [{"primary": ["local"]}]
  context_window_fallbacks: [{"primary": ["secondary"]}]
litellm_settings:
  success_callback: ["langsmith"]
  drop_params: true

TASK 3 — Create .env.example with ALL required variables, each with a comment explaining what it is:
Variables needed: POSTGRES_USER, POSTGRES_PASSWORD, POSTGRES_DB, POSTGRES_HOST, POSTGRES_PORT,
REDIS_URL, QDRANT_HOST, QDRANT_PORT, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, MINIO_ENDPOINT,
KEYCLOAK_URL, KEYCLOAK_REALM, KEYCLOAK_CLIENT_ID, KEYCLOAK_CLIENT_SECRET,
ANTHROPIC_API_KEY, OPENAI_API_KEY, LITELLM_URL, OLLAMA_BASE_URL,
LANGSMITH_API_KEY, LANGSMITH_PROJECT, TAVILY_API_KEY,
SECRET_KEY (for FastAPI sessions), ENVIRONMENT (development/staging/production)

TASK 4 — Create Python workspace config:
- packages/shared/pyproject.toml: package name "shared", deps: pydantic>=2.0, sqlalchemy>=2.0, alembic, asyncpg
- packages/rag/pyproject.toml: package name "rag", deps: pymupdf, qdrant-client, llama-index-core, rank-bm25, sentence-transformers, celery[redis], httpx
- packages/agents/pyproject.toml: package name "agents", deps: langgraph>=0.2, langchain-anthropic, langchain-openai, langsmith, litellm
- apps/api/pyproject.toml: package name "api", deps: fastapi>=0.111, uvicorn[standard], python-jose[cryptography], pydantic-settings, structlog, flower

TASK 5 — Create Node workspace:
- Root package.json with workspaces: ["apps/web"]
- apps/web/package.json with Next.js 14, shadcn/ui, tailwindcss, zustand, @tanstack/react-query, recharts, next-auth

TASK 6 — Create pre-commit config (.pre-commit-config.yaml):
- ruff (lint + format) for Python
- mypy for Python type checking  
- eslint for TypeScript
- prettier for TS/JSON/CSS

TASK 7 — Create .gitignore covering Python (__pycache__, .venv, *.pyc), Node (node_modules, .next), env files (.env, .env.local), and IDE files.

CONSTRAINTS:
- Do not write any application logic yet — only scaffolding and config
- All secrets must come from environment variables, never hardcoded
- Docker Compose must use depends_on with service_healthy conditions so services start in correct order

ACCEPTANCE CRITERIA:
1. Running `docker compose -f infra/docker-compose.yml up -d` starts all 7 services
2. `docker compose ps` shows all services as healthy within 2 minutes
3. MinIO console accessible at http://localhost:9001
4. Keycloak admin console accessible at http://localhost:8080
5. `curl http://localhost:6333/healthz` returns {"status":"ok"}
6. `curl http://localhost:4000/health` returns LiteLLM health response
```

---

## PROMPT 0.2 — Database Schema, Migrations & RLS

```
You are implementing the PostgreSQL database schema for a multi-tenant Stock Analyst AI platform.
The Docker Compose stack from the previous step is running with PostgreSQL 16 at localhost:5432.

CONTEXT:
Multi-tenancy is enforced via PostgreSQL Row-Level Security (RLS). Every query that touches
tenant-scoped data must set `app.current_tenant_id` as a session variable — the RLS policies
use this to filter rows automatically. This means no application code ever needs a WHERE tenant_id=?
clause; the database enforces isolation transparently.

TASK 1 — Set up Alembic:
- Initialize Alembic in the migrations/ directory
- Configure alembic.ini to use async SQLAlchemy with asyncpg driver
- env.py must import the metadata from packages/shared/models.py (create this file)

TASK 2 — Create packages/shared/models.py with SQLAlchemy ORM models AND Pydantic schemas:

SQLAlchemy tables (create in this FK-safe order):

1. tenants:
   - id: UUID primary key, default uuid4
   - name: String(255) not null
   - plan: Enum('starter', 'professional', 'enterprise') not null
   - settings: JSONB default {}
   - created_at: DateTime with timezone, default now()

2. users:
   - id: UUID primary key
   - tenant_id: UUID FK → tenants.id ON DELETE CASCADE
   - email: String(255) not null unique
   - role: Enum('viewer', 'analyst', 'senior_analyst', 'admin') not null
   - created_at: DateTime with timezone, default now()

3. industries:
   - id: UUID primary key
   - name: String(255) not null unique
   - primer_content: Text (nullable — null until Industry Agent runs)
   - primer_citations: JSONB default []
   - word_count: Integer nullable
   - llm_used: String(100) nullable
   - created_at: DateTime with timezone, default now()
   - updated_at: DateTime with timezone, nullable

4. coverages:
   - id: UUID primary key
   - tenant_id: UUID FK → tenants.id ON DELETE CASCADE
   - ticker: String(20) not null
   - company_name: String(500) not null
   - exchange: String(50) not null
   - industry_id: UUID FK → industries.id nullable
   - created_by: UUID FK → users.id
   - status: Enum('setup', 'active', 'archived') default 'setup'
   - document_count: Integer default 0
   - last_updated: DateTime with timezone nullable
   - created_at: DateTime with timezone, default now()
   - UniqueConstraint(tenant_id, ticker, exchange)

5. documents:
   - id: UUID primary key
   - coverage_id: UUID FK → coverages.id ON DELETE CASCADE
   - tenant_id: UUID FK → tenants.id ON DELETE CASCADE
   - file_name: String(500) not null
   - filing_type: String(50) not null  # "10-K", "10-Q", "8-K", "transcript", "custom"
   - period: String(50) not null  # "FY2024", "Q3 2024"
   - source: String(100) not null  # "SEC EDGAR", "user_upload", "IR page"
   - source_url: String(1000) nullable
   - storage_path: String(1000) not null  # MinIO path
   - page_count: Integer nullable
   - chunk_count: Integer default 0
   - ingested_at: DateTime with timezone nullable
   - quality_score: Float nullable
   - ingest_status: Enum('pending', 'indexing', 'indexed', 'failed', 'review_needed') default 'pending'
   - file_hash: String(64) nullable  # SHA-256, for duplicate detection

6. research_outputs:
   - id: UUID primary key
   - coverage_id: UUID FK → coverages.id ON DELETE CASCADE
   - tenant_id: UUID FK → tenants.id ON DELETE CASCADE
   - output_type: Enum('industry_primer', 'lynch_pitch', 'munger_invert', 'quarterly_update', 'kpi_snapshot')
   - content: Text not null  # Markdown with inline citations
   - citations: JSONB default []
   - citation_coverage_pct: Float nullable
   - approved_by_enforcer: Boolean default false
   - enforcer_status: Enum('pending', 'approved', 'partial', 'failed') default 'pending'
   - llm_used: String(100) nullable
   - tokens_used: Integer default 0
   - generated_at: DateTime with timezone default now()
   - approved_at: DateTime with timezone nullable
   - approved_by: UUID FK → users.id nullable
   - version: Integer default 1

7. kpi_timeseries:
   - id: UUID primary key
   - coverage_id: UUID FK → coverages.id ON DELETE CASCADE
   - kpi_name: String(100) not null
   - period: String(50) not null
   - period_type: Enum('annual', 'quarterly') not null
   - value: Float not null
   - unit: String(50) not null  # "USD_millions", "percentage", "count"
   - citation: JSONB not null  # serialized Citation object
   - is_restated: Boolean default false
   - restatement_note: Text nullable
   - extracted_at: DateTime with timezone default now()

8. agent_audit_log (append-only — no updates or deletes ever):
   - id: UUID primary key
   - tenant_id: UUID not null  # no FK — log must survive tenant deletion
   - coverage_id: UUID nullable
   - agent_name: String(100) not null
   - action: String(100) not null
   - input_hash: String(64) nullable
   - output_id: UUID nullable
   - llm_used: String(100) nullable
   - tokens_used: Integer default 0
   - latency_ms: Integer nullable
   - created_at: DateTime with timezone default now()
   - metadata: JSONB default {}

9. task_queue:
   - id: UUID primary key
   - coverage_id: UUID FK → coverages.id ON DELETE CASCADE nullable
   - tenant_id: UUID FK → tenants.id ON DELETE CASCADE
   - task_type: String(100) not null
   - status: Enum('queued', 'running', 'completed', 'failed', 'cancelled') default 'queued'
   - celery_task_id: String(255) nullable
   - created_at: DateTime with timezone default now()
   - started_at: DateTime with timezone nullable
   - completed_at: DateTime with timezone nullable
   - error: Text nullable
   - result: JSONB nullable

TASK 3 — Create the Alembic migration:
Generate migration file migrations/versions/001_initial_schema.py that:
1. Creates all 9 tables above in FK-safe order
2. Enables RLS on these tenant-scoped tables: users, coverages, documents, research_outputs, kpi_timeseries, task_queue
3. Creates RLS policy on each enabled table:
   CREATE POLICY tenant_isolation ON {table}
   USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);
4. For agent_audit_log: enable RLS but policy uses tenant_id column (not a FK, just a UUID column)
5. Grants REVOKE DELETE ON agent_audit_log FROM PUBLIC; and REVOKE UPDATE ON agent_audit_log FROM PUBLIC; to enforce append-only

TASK 4 — Create packages/shared/config.py:
- Settings class using pydantic-settings BaseSettings
- Reads all values from environment variables defined in .env.example
- Includes a get_db_url() method returning the async SQLAlchemy connection string

TASK 5 — Create a seed script scripts/seed_dev.py:
- Creates 2 test tenants: "Acme Capital" (tenant-a) and "Beta Fund" (tenant-b)
- Creates 4 users in tenant-a: one per role (viewer, analyst, senior_analyst, admin)
- Creates 1 admin user in tenant-b
- Creates 3 industries: "Enterprise Software", "Semiconductor Capital Equipment", "Regional Banking"
- Prints created IDs for use in testing

CONSTRAINTS:
- Use async SQLAlchemy throughout (asyncpg driver)
- All migrations must be reversible (downgrade() must drop tables in reverse FK order)
- RLS policies must use `current_setting('app.current_tenant_id', true)` — the `true` argument makes it return NULL instead of raising an error if the variable is not set
- The audit log append-only constraint must be enforced at the DB level, not just application level

ACCEPTANCE CRITERIA:
1. `alembic upgrade head` completes without errors on a fresh database
2. `psql -c "\d coverages"` shows all columns and the RLS indicator
3. `psql -c "SELECT tablename, rowsecurity FROM pg_tables WHERE schemaname='public'"` shows rowsecurity=true for all 6 tenant-scoped tables
4. Running seed_dev.py creates all test records without errors
5. Direct SQL as tenant-a cannot retrieve tenant-b's coverages (test by setting app.current_tenant_id to tenant-a's id)
```

---

## PROMPT 0.3 — FastAPI Application: Auth, Tenant Middleware & Health Endpoints

```
You are implementing the FastAPI backend skeleton for a multi-tenant Stock Analyst AI platform.
The database schema from the previous step is in place with RLS enabled.
The Docker Compose stack is running with Keycloak at http://localhost:8080.

CONTEXT:
Authentication uses Keycloak JWTs (RS256). Every authenticated request carries a JWT with:
- sub: user UUID
- tenant_id: custom claim (set by Keycloak mapper)
- realm_access.roles: array containing the user's role
The tenant middleware extracts tenant_id from the JWT and sets `app.current_tenant_id` as a
PostgreSQL session variable on every database connection, activating RLS transparently.

TASK 1 — Create apps/api/main.py:
- FastAPI app with title "Stock Analyst AI API", version "1.0.0"
- Lifespan context manager: on startup verify DB connection, log all service health; on shutdown close connection pools
- Add middleware in this order: CORSMiddleware (allow origins from settings), TenantMiddleware (custom), then routers
- Include routers: health, coverages (stub), documents (stub), tasks (stub), outputs (stub), admin (stub)
- OpenAPI docs at /docs (disable in production via ENVIRONMENT check)

TASK 2 — Create apps/api/middleware/auth.py:
Implement get_current_user() as a FastAPI dependency:
- Extract Bearer token from Authorization header
- Fetch Keycloak public keys from {KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/certs
- Cache the JWKS for 5 minutes (use a module-level dict with timestamp)
- Validate token: signature, expiry, issuer
- Extract from token payload: sub → user_id, tenant_id claim, realm_access.roles[0] → role
- Return a CurrentUser dataclass: user_id (UUID), tenant_id (UUID), role (str), email (str)
- Raise HTTPException(401) for invalid/expired tokens
- Raise HTTPException(403) for missing tenant_id claim

Create a role_required(minimum_role) dependency factory:
- Role hierarchy: viewer=0, analyst=1, senior_analyst=2, admin=3
- Raises HTTPException(403) if user's role is below minimum_role

TASK 3 — Create apps/api/middleware/tenant.py:
Implement TenantMiddleware as a Starlette BaseHTTPMiddleware:
- Skip tenant injection for paths: /health, /docs, /openapi.json, /redoc
- For all other paths: verify JWT is present and valid (call get_current_user logic)
- Store tenant_id in request.state.tenant_id
- For every SQLAlchemy async session used in this request, execute:
  await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
- Implement this by overriding the session factory to inject the SET LOCAL before every transaction

TASK 4 — Create apps/api/routers/health.py:
GET /health:
- No authentication required
- Returns: {"status": "ok", "version": "1.0.0", "environment": settings.ENVIRONMENT}

GET /health/deep:
- No authentication required
- Checks each service and returns status:
  - PostgreSQL: execute SELECT 1
  - Redis: ping
  - Qdrant: GET http://qdrant:6333/healthz
  - MinIO: list buckets (if accessible)
  - LiteLLM: GET http://litellm:4000/health
- Returns:
  {
    "status": "healthy" | "degraded" | "unhealthy",
    "services": {
      "postgres": {"status": "ok" | "error", "latency_ms": int},
      "redis": {"status": "ok" | "error", "latency_ms": int},
      "qdrant": {"status": "ok" | "error", "latency_ms": int},
      "minio": {"status": "ok" | "error", "latency_ms": int},
      "litellm": {"status": "ok" | "error", "latency_ms": int}
    }
  }
- Overall status: "healthy" if all ok, "degraded" if 1-2 errors, "unhealthy" if 3+ errors

TASK 5 — Create stub routers (return 501 Not Implemented for now):
- apps/api/routers/coverages.py — routes: POST/GET /coverages, GET/DELETE /coverages/{id}
- apps/api/routers/documents.py — routes: POST/GET /coverages/{id}/documents, DELETE /coverages/{id}/documents/{doc_id}
- apps/api/routers/tasks.py — routes: GET/DELETE /tasks/{task_id}
- apps/api/routers/outputs.py — routes: GET /coverages/{id}/outputs, GET/POST /coverages/{id}/outputs/{output_id}
- apps/api/routers/admin.py — routes: GET /admin/tenants, GET /admin/usage, GET /admin/agents/health

TASK 6 — Create apps/api/db.py:
- Async SQLAlchemy engine using asyncpg
- AsyncSessionLocal factory
- get_db() dependency that yields an AsyncSession
- The session must execute SET LOCAL app.current_tenant_id before any query — wire this into get_db() by checking request.state for tenant_id

TASK 7 — Create integration test tests/integration/test_auth.py:
Test cases (use httpx.AsyncClient against the running app):
1. GET /health returns 200 without auth
2. GET /health/deep returns 200 and all services are "ok"
3. GET /coverages without Bearer token returns 401
4. GET /coverages with expired JWT returns 401
5. GET /coverages with valid tenant-a JWT returns 200 (empty list, not 403)
6. GET /coverages/{tenant_b_coverage_id} with tenant-a JWT returns 403 or empty (RLS blocks it)

CONSTRAINTS:
- Use python-jose for JWT validation, not PyJWT
- JWKS cache must be thread-safe (use asyncio.Lock)
- All database operations must be async — no sync SQLAlchemy calls anywhere
- The tenant SET LOCAL must happen inside the transaction, not before it (use event listeners or explicit calls at start of each request handler)
- Error responses must follow RFC 7807 (Problem Details): {"type": "...", "title": "...", "status": 400, "detail": "..."}

ACCEPTANCE CRITERIA:
1. `uvicorn apps.api.main:app --reload` starts without errors
2. GET /health/deep returns all services as "ok"
3. curl with no token → 401; curl with valid token → depends on endpoint
4. Integration tests in test_auth.py all pass
5. mypy apps/api/ runs with zero errors
```

---

## PROMPT 0.4 — Keycloak Realm Configuration & Next.js Auth Shell

```
You are implementing the authentication configuration and frontend shell for the Stock Analyst AI platform.
FastAPI is running with JWT validation. Keycloak is running at http://localhost:8080.

TASK 1 — Create infra/keycloak/realm-export.json:
A complete Keycloak realm export JSON that, when imported, creates:

Realm settings:
- realm: "stock-analyst"
- displayName: "Stock Analyst AI"
- enabled: true
- registrationAllowed: false
- loginWithEmailAllowed: true
- accessTokenLifespan: 900 (15 minutes)
- refreshTokenMaxReuse: 0

Clients:
1. "stock-analyst-api" (confidential, service account):
   - clientAuthenticatorType: client-secret
   - serviceAccountsEnabled: true
   - standardFlowEnabled: false
   - directAccessGrantsEnabled: false

2. "stock-analyst-web" (public, PKCE, browser client):
   - publicClient: true
   - standardFlowEnabled: true
   - pkceCodeChallengeMethod: S256
   - redirectUris: ["http://localhost:3000/*", "https://*.stock-analyst.internal/*"]
   - webOrigins: ["http://localhost:3000", "https://*.stock-analyst.internal"]
   - fullScopeAllowed: true

Roles (realm roles):
- viewer, analyst, senior_analyst, admin

Protocol Mapper on "stock-analyst-web" client:
- Name: "tenant_id"
- Mapper type: "User Attribute"
- User attribute: "tenant_id"
- Token claim name: "tenant_id"
- Claim JSON type: "String"
- Add to ID token: true
- Add to access token: true

Test users (with tenant_id attribute set):
- analyst-a@test.com / TestPass123! → role: analyst, tenant_id: "00000000-0000-0000-0000-000000000001"
- senior-a@test.com / TestPass123! → role: senior_analyst, tenant_id: "00000000-0000-0000-0000-000000000001"
- admin-a@test.com / TestPass123! → role: admin, tenant_id: "00000000-0000-0000-0000-000000000001"
- viewer-a@test.com / TestPass123! → role: viewer, tenant_id: "00000000-0000-0000-0000-000000000001"
- analyst-b@test.com / TestPass123! → role: analyst, tenant_id: "00000000-0000-0000-0000-000000000002"

TASK 2 — Scaffold Next.js 14 app at apps/web/:
Run: npx create-next-app@14 with: TypeScript, Tailwind, App Router, src/ directory = NO (use app/ directly), import alias @/*

TASK 3 — Install and configure NextAuth.js (next-auth@4):
- apps/web/app/api/auth/[...nextauth]/route.ts
- Provider: KeycloakProvider with:
  clientId: process.env.NEXT_PUBLIC_KEYCLOAK_CLIENT_ID
  clientSecret: "" (empty — public client)
  issuer: process.env.NEXT_PUBLIC_KEYCLOAK_URL/realms/stock-analyst
- Session strategy: "jwt"
- Callbacks:
  jwt(): extract tenant_id and role from Keycloak token, add to NextAuth JWT
  session(): expose user.tenant_id and user.role on the session object
- Types: extend next-auth types in apps/web/types/next-auth.d.ts to include tenant_id: string and role: string on Session.user

TASK 4 — Create the application layout:
apps/web/app/layout.tsx:
- SessionProvider wrapping the app
- Inter font
- Import globals.css with Tailwind

apps/web/app/(auth)/layout.tsx:
- Centered card layout for login page

apps/web/app/(auth)/login/page.tsx:
- "Sign in with your organization" button
- calls signIn("keycloak")
- Shows company logo placeholder

apps/web/app/(protected)/layout.tsx:
- Server component that calls getServerSession()
- Redirects to /login if no session
- Renders sidebar navigation + main content area

apps/web/components/layout/sidebar.tsx:
Navigation items (with icons using lucide-react):
- Coverages (/coverages) — visible to all roles
- Admin (/admin) — only visible if session.user.role === "admin"
- Shows user email and role badge at bottom
- Logout button using signOut()

apps/web/app/(protected)/coverages/page.tsx:
- Placeholder: "Coverage list coming soon"
- Shows: "Logged in as {email} ({role})" for verification

TASK 5 — Configure shadcn/ui:
Run: npx shadcn-ui@latest init with: style=default, base color=slate, CSS variables=yes
Install components: button, card, badge, dialog, input, label, dropdown-menu, avatar, tooltip

TASK 6 — Create apps/web/lib/api.ts:
- Base fetch wrapper that:
  - Gets the NextAuth session JWT
  - Attaches it as Bearer token to all API requests
  - Base URL from process.env.NEXT_PUBLIC_API_URL
  - Throws typed ApiError for non-2xx responses

CONSTRAINTS:
- The Keycloak realm export JSON must be valid JSON that Keycloak can import on container startup without manual steps
- NextAuth session token must include tenant_id — the FastAPI backend relies on this
- Do not use the Pages Router anywhere — App Router only
- Role-based rendering must check the role from the session, not from an API call

ACCEPTANCE CRITERIA:
1. docker compose restart keycloak → Keycloak starts with the realm pre-configured
2. All 5 test users can log in at http://localhost:8080/realms/stock-analyst/account
3. npm run dev in apps/web/ starts Next.js at localhost:3000
4. Navigating to /coverages redirects to login if not authenticated
5. After login as analyst-a, sidebar shows Coverages but NOT Admin
6. After login as admin-a, sidebar shows both Coverages and Admin
7. Session object contains tenant_id and role (verify in /api/auth/session)
```

---

## PROMPT 0.5 — Gitea CI Pipeline & MinIO Bucket Policies

```
You are implementing CI/CD and storage policies for the Stock Analyst AI platform.
The monorepo, Docker Compose stack, database, FastAPI backend, and Next.js frontend are all in place.

TASK 1 — Create Gitea Actions CI workflow at .gitea/workflows/ci.yml:
The workflow runs on push to any branch and on pull_request targeting main.

Jobs (run in parallel where possible, sequential where dependent):

job: lint-python
  runs-on: ubuntu-latest
  steps:
    - checkout
    - setup Python 3.12
    - pip install ruff mypy
    - ruff check packages/ apps/api/ (fail on any error)
    - ruff format --check packages/ apps/api/ (fail if not formatted)
    - mypy packages/shared packages/rag packages/agents apps/api --strict --ignore-missing-imports

job: lint-frontend
  runs-on: ubuntu-latest
  steps:
    - checkout
    - setup Node 20
    - npm ci in apps/web/
    - npm run lint (eslint)
    - npx tsc --noEmit in apps/web/

job: test-unit (depends on lint-python passing)
  runs-on: ubuntu-latest
  steps:
    - checkout
    - setup Python 3.12
    - pip install pytest pytest-asyncio pytest-cov
    - pip install -e packages/shared -e packages/rag -e packages/agents
    - pytest packages/ tests/unit/ -v --cov=packages --cov-report=xml --ignore=tests/integration
    - Fail if coverage < 80%

job: test-migrations (depends on lint-python passing)
  runs-on: ubuntu-latest
  services:
    postgres: image postgres:16, env POSTGRES_USER=test POSTGRES_PASSWORD=test POSTGRES_DB=test
  steps:
    - checkout
    - setup Python 3.12
    - pip install alembic asyncpg sqlalchemy
    - pip install -e packages/shared
    - Set DATABASE_URL env var pointing to the service postgres
    - alembic upgrade head
    - alembic downgrade base (verify reversibility)
    - alembic upgrade head (verify idempotent)

job: test-infra (manual trigger only, not on every push — use workflow_dispatch)
  steps:
    - checkout
    - docker compose -f infra/docker-compose.yml up -d --wait
    - curl --retry 10 --retry-delay 3 http://localhost:8080/health/ready (Keycloak)
    - curl http://localhost:6333/healthz (Qdrant)
    - curl http://localhost:4000/health (LiteLLM)
    - python -m pytest tests/integration/ -v (full integration suite)
    - docker compose down

TASK 2 — Create scripts/setup_minio.py:
A script that sets up per-tenant MinIO buckets for the development environment.
The script must be idempotent (safe to run multiple times).

Using the minio Python client (pip install minio):

def setup_tenant_bucket(client, tenant_id: str):
    bucket_name = f"stocks-{tenant_id}"
    # Create bucket if not exists
    # Set bucket policy: only allow access with the service account credentials
    # The policy JSON should:
    #   - Allow s3:GetObject, s3:PutObject, s3:DeleteObject on arn:aws:s3:::stocks-{tenant_id}/*
    #   - Deny all actions from any principal that is not the service account
    # For dev simplicity: use MinIO's private policy (no public access)
    # Create folder structure: {bucket}/raw/, {bucket}/processed/

For the two dev tenants:
- tenant_id: "00000000-0000-0000-0000-000000000001" → bucket: stocks-00000000-0000-0000-0000-000000000001
- tenant_id: "00000000-0000-0000-0000-000000000002" → bucket: stocks-00000000-0000-0000-0000-000000000002

Also create: a shared "models" bucket for storing downloaded embedding models and ML artifacts.

TASK 3 — Create apps/api/services/storage.py:
MinIO client wrapper:

class StorageService:
    def __init__(self, endpoint: str, access_key: str, secret_key: str)
    
    async def upload_file(self, tenant_id: str, coverage_id: str, file_type: str, 
                          file_name: str, content: bytes) -> str:
        # Uploads to: stocks-{tenant_id}/{file_type}/{coverage_id}/{file_name}
        # Returns the MinIO object path (not a pre-signed URL)
    
    async def get_presigned_url(self, tenant_id: str, object_path: str, 
                                 expires_minutes: int = 15) -> str:
        # Validates that object_path starts with stocks-{tenant_id}/ (prevent cross-tenant access)
        # Returns pre-signed GET URL valid for expires_minutes
        # Raises ValueError if object_path belongs to a different tenant
    
    async def delete_file(self, tenant_id: str, object_path: str) -> None:
        # Same tenant validation before deletion
    
    async def file_exists(self, object_path: str) -> bool:
        # Check if object exists (used for hash-based duplicate detection)

TASK 4 — Create unit tests tests/unit/test_storage.py:
Mock the MinIO client and test:
1. upload_file generates correct path format
2. get_presigned_url raises ValueError when object_path has different tenant_id
3. delete_file raises ValueError when object_path has different tenant_id
4. file_exists returns True/False correctly

TASK 5 — Create a Makefile at the repo root with developer shortcuts:
make up        → docker compose up -d
make down      → docker compose down
make logs      → docker compose logs -f
make migrate   → alembic upgrade head
make seed      → python scripts/seed_dev.py && python scripts/setup_minio.py
make test      → pytest tests/unit/ -v
make lint      → ruff check packages/ apps/api/ && mypy packages/ apps/api/
make dev-api   → uvicorn apps.api.main:app --reload --port 8000
make dev-web   → (cd apps/web && npm run dev)
make pull-model → docker compose exec ollama ollama pull nomic-embed-text:v1.5

CONSTRAINTS:
- CI jobs must not require secrets for unit and lint jobs (mock all external services)
- The MinIO tenant isolation (get_presigned_url raising on wrong tenant) must be enforced in code because MinIO itself does not enforce this at the pre-signed URL level in all configurations
- The Makefile targets must work on Linux and macOS; use #!/usr/bin/env bash for any embedded scripts

ACCEPTANCE CRITERIA:
1. Pushing to a branch triggers CI; lint and unit test jobs complete in <3 minutes
2. Migration job: alembic upgrade head + downgrade base + upgrade head with no errors
3. python scripts/setup_minio.py runs and creates both tenant buckets
4. StorageService.get_presigned_url raises ValueError on cross-tenant object path
5. make seed runs completely (minio + db seed, no errors)
```

---

## PROMPT 1.1 — SEC EDGAR Connector & PDF Parser

```
You are implementing the document acquisition layer for the Stock Analyst AI platform.
Phase 0 is complete: FastAPI is running, PostgreSQL has the schema, MinIO has tenant buckets.
Working directory: packages/rag/

CONTEXT:
The Document Ingestion Agent needs to pull filings directly from SEC EDGAR's public API.
This is the authoritative, free source for 10-K, 10-Q, and 8-K filings.
Key SEC EDGAR APIs:
- Company search: https://efts.sec.gov/LATEST/search-index?q="{ticker}"&dateRange=custom&startdt={year}-01-01&enddt={year}-12-31&forms={form_type}
- Filing detail: https://data.sec.gov/submissions/CIK{cik_padded}.json (company metadata + filing list)
- Document index: https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{accession_no}-index.json
SEC rate limit: max 10 requests/second; implement polite throttling.

TASK 1 — Create packages/rag/connectors/sec_edgar.py:

Data classes first:
@dataclass
class FilingMeta:
    ticker: str
    cik: str
    form_type: str          # "10-K", "10-Q", "8-K"
    accession_number: str   # "0000320193-23-000106"
    filed_date: date
    period_of_report: str   # "FY2023", "Q3 2023" (normalized)
    primary_document_url: str
    filing_index_url: str

@dataclass
class FilingResult:
    meta: FilingMeta
    minio_path: str         # where it was stored
    file_size_bytes: int
    download_success: bool
    error: str | None

class SECEdgarConnector:
    def __init__(self, minio_storage: StorageService, rate_limit_rps: float = 8.0):
        # Use asyncio token bucket for rate limiting

    async def get_cik(self, ticker: str) -> str:
        # Fetch from https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=&dateb=&owner=include&count=10&search_text=&action=getcompany
        # Or use the tickers.json endpoint: https://www.sec.gov/files/company_tickers.json
        # Cache CIK lookups in memory (tickers don't change)

    async def list_filings(self, ticker: str, form_type: str, 
                           years: int = 5) -> list[FilingMeta]:
        # Get CIK, then fetch submission JSON from data.sec.gov
        # Filter by form_type and last {years} years
        # Normalize period_of_report to "FY2023" or "Q3 2023" format
        # Return list sorted by filed_date descending

    async def fetch_filing(self, ticker: str, form_type: str, 
                           year: int) -> FilingResult | None:
        # Find the filing for the given year
        # For 10-K: match period_of_report year; for 10-Q: find Q1/Q2/Q3/Q4 for that year
        # Returns None if no filing found

    async def download_to_minio(self, meta: FilingMeta, 
                                 tenant_id: str, coverage_id: str) -> FilingResult:
        # Download primary document (usually the .htm or .pdf version)
        # Prefer .pdf if available, else .htm
        # Store at: stocks-{tenant_id}/raw/{coverage_id}/{accession_number}.pdf
        # Return FilingResult with minio_path
        
    async def _fetch_with_rate_limit(self, url: str) -> bytes:
        # Enforce rate limiting (token bucket)
        # Add required User-Agent header: "StockAnalystAI contact@example.com"
        # Retry up to 3 times on 429 or 503 with exponential backoff
        # Raise after 3 failures

TASK 2 — Create packages/rag/ingestion/parsers/pdf_parser.py:

@dataclass
class TextBlock:
    text: str
    page_number: int
    block_type: str  # "paragraph", "heading", "list_item", "caption"
    font_size: float
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1

@dataclass
class ParsedPage:
    page_number: int
    text_blocks: list[TextBlock]
    raw_text: str               # concatenated text, in reading order
    text_coverage_pct: float    # chars extracted / estimated page chars
    has_tables: bool            # True if Docling should process this page

@dataclass
class ParsedDocument:
    document_id: str
    file_name: str
    pages: list[ParsedPage]
    total_pages: int
    overall_text_coverage: float
    parser_used: str            # "pymupdf" or "unstructured"
    sections: dict[str, str]    # section_name → full text content

class PDFParser:
    def parse(self, file_path: Path, document_id: str, file_name: str) -> ParsedDocument:
        # Stage 1: try PyMuPDF (fitz)
        # Stage 2: if overall_text_coverage < 0.50, switch to Unstructured.io
        
    def _parse_with_pymupdf(self, file_path: Path) -> list[ParsedPage]:
        # Use fitz.open()
        # For each page: extract text with page.get_text("dict") to get block-level info
        # Determine block_type heuristically from font size (largest = heading)
        # Compute text_coverage_pct: len(extracted_chars) / (page.rect.width * page.rect.height / 100)
        # Mark has_tables=True if any block contains grid-like patterns (multiple tabs or │ chars)
        
    def _parse_with_unstructured(self, file_path: Path) -> list[ParsedPage]:
        # from unstructured.partition.pdf import partition_pdf
        # Use strategy="hi_res" for scanned documents
        # Map Unstructured element types to our TextBlock block_type enum
        
    def _detect_sections(self, pages: list[ParsedPage]) -> dict[str, str]:
        # Common SEC filing sections to detect:
        # "cover", "business", "risk_factors", "mda", "financial_statements", 
        # "notes_to_financials", "controls", "exhibits"
        # Match by heading text patterns (case-insensitive regex)
        # Return dict: section_name → full text of that section

TASK 3 — Create unit tests tests/unit/test_sec_edgar.py:
Mock all HTTP calls with httpx.MockTransport:
1. get_cik("AAPL") returns the correct CIK "0000320193"
2. list_filings("AAPL", "10-K", years=3) returns 3 FilingMeta objects
3. Rate limiting: 15 rapid calls → all succeed but take ≥1.5s (throttled to 8/s max)
4. 429 response → retried 3 times with backoff → FilingResult with error after 3 failures

Create unit tests tests/unit/test_pdf_parser.py:
Use a small synthetic PDF created with reportlab in the test fixture:
1. Simple text PDF → parsed with PyMuPDF; text_coverage_pct > 0.8
2. Very low text coverage → falls back to Unstructured parser
3. Heading detection: page with large font text → block_type == "heading"
4. Section detection: text containing "ITEM 1A. RISK FACTORS" → sections["risk_factors"] populated

CONSTRAINTS:
- SEC EDGAR requires User-Agent header — without it you get 403. Always include: "StockAnalystAI yourname@example.com"
- Rate limiting must be async-safe (use asyncio.Semaphore or token bucket, not time.sleep)
- PyMuPDF must be imported as `import fitz` (the package is pymupdf but the module is fitz)
- Unstructured.io is a heavy dependency — lazy import it inside _parse_with_unstructured() so it doesn't slow startup
- The ParsedDocument.sections detection is best-effort; an empty dict is acceptable for unusual filing formats

ACCEPTANCE CRITERIA:
1. SECEdgarConnector().list_filings("AAPL", "10-K", years=3) returns 3 filings with correct metadata
2. Fetching and downloading a real 10-K stores it in MinIO and returns a valid minio_path
3. Parsing a real 100-page 10-K with PDFParser completes in <10 seconds
4. All unit tests pass with `pytest tests/unit/test_sec_edgar.py tests/unit/test_pdf_parser.py -v`
```

---

## PROMPT 1.2 — Table Extractor & Financial Normalizer

```
You are implementing document processing utilities for the Stock Analyst AI platform.
The SEC EDGAR connector and PDF parser from the previous step are complete.
Working directory: packages/rag/

CONTEXT:
Financial tables in SEC filings are critical — they contain the raw numbers that KPI Tracker
and Earnings Monitor agents will cite. Tables must be extracted as structured data (not flattened text),
because the Citation Enforcer will verify that cited numbers appear in indexed chunks.
The Financial Normalizer ensures all values are in a consistent unit so the KPI time-series
is comparable across documents that may express values in millions, billions, or different currencies.

TASK 1 — Create packages/rag/ingestion/parsers/table_extractor.py:

@dataclass
class TableCell:
    row: int
    col: int
    value: str          # raw string as it appears in the document
    is_header: bool

@dataclass
class ExtractedTable:
    page_number: int
    table_index: int    # 0-based index of table on that page
    caption: str | None # text immediately above the table, if detectable
    section_name: str   # which section this table came from
    cells: list[TableCell]
    column_headers: list[str]
    row_headers: list[str]
    as_markdown: str    # pipe-delimited markdown representation
    as_json: dict       # {"headers": [...], "rows": [[...],...]}
    document_id: str
    filing_type: str
    period: str

class TableExtractor:
    def extract_tables(self, file_path: Path, parsed_document: ParsedDocument,
                       document_id: str, filing_type: str, period: str) -> list[ExtractedTable]:
        # Use Docling for table detection and extraction
        # from docling.document_converter import DocumentConverter
        # converter = DocumentConverter()
        # result = converter.convert(str(file_path))
        # Iterate result.document.tables
        # For each table: map to ExtractedTable, detect caption from surrounding text
        # Cross-reference page_number from ParsedDocument to get section_name
        
    def _infer_caption(self, table, parsed_document: ParsedDocument) -> str | None:
        # Look at the paragraph text immediately before the table on the same page
        # If that text is <150 chars and ends without a period, it's likely a caption
        
    def _table_to_markdown(self, cells: list[TableCell], 
                            col_headers: list[str]) -> str:
        # Build GitHub-flavored markdown table
        # Header row | separator row | data rows
        
    def _table_to_json(self, cells: list[TableCell], 
                        col_headers: list[str], row_headers: list[str]) -> dict:
        # {"headers": col_headers, "rows": [{"label": row_header, "values": {col: value}}]}

TASK 2 — Create packages/rag/ingestion/parsers/financial_normalizer.py:

This module normalizes raw financial values extracted from text or tables into a standard form.

@dataclass
class NormalizedValue:
    raw_string: str         # original as found in document, e.g. "$1.23 billion"
    numeric_value: float    # e.g. 1230.0
    unit: str               # "USD_millions", "percentage", "count", "ratio"
    currency: str | None    # "USD", "EUR", "GBP", None for non-monetary
    is_negative: bool       # True for values in parentheses e.g. (452) or negative
    confidence: float       # 0-1, how confident the parse is

@dataclass 
class NormalizedPeriod:
    raw_string: str     # original e.g. "fiscal year ended December 31, 2024"
    period_label: str   # "FY2024" or "Q3 2024"
    period_type: str    # "annual" or "quarterly"
    fiscal_year: int
    quarter: int | None

class FinancialNormalizer:
    
    def normalize_value(self, raw: str, context_unit: str | None = None) -> NormalizedValue:
        # Handle these patterns (with comprehensive regex):
        # Billions: "$1.23B", "$1.23 billion", "1.23B", "1,234.5 million" → multiply to get millions
        # Millions: "$1.23M", "$1.23 million", "1,234" (in-context) → value in millions
        # Thousands: "$1.23K", "$1,234" (when context says "in thousands") → divide to get millions
        # Percentages: "12.3%", "12.3 percent", "(12.3)%" → unit="percentage"
        # Shares: "4.5M shares", "4,500,000 shares" → unit="count"
        # Negatives: "(452)" or "(1.2B)" or "-452" → is_negative=True, value positive
        # N/A, "—", "-", "n/m" → return NaN with confidence=0.0
        
    def normalize_period(self, raw: str) -> NormalizedPeriod:
        # Handle these patterns:
        # Annual: "fiscal year 2024", "FY2024", "FY'24", "year ended Dec 31, 2024",
        #         "twelve months ended December 31, 2024", "annual 2024"
        # Quarterly: "Q1 2024", "Q1'24", "first quarter 2024", "three months ended Mar 31, 2024"
        # "third quarter fiscal 2024" → Q3 2024
        # For annual: period_label = "FY{year}", period_type = "annual", quarter = None
        # For quarterly: period_label = "Q{n} {year}", period_type = "quarterly"
        
    def extract_values_from_text(self, text: str) -> list[tuple[str, NormalizedValue]]:
        # Find all financial values in a text string
        # Returns list of (original_matched_string, NormalizedValue)
        # Used by KPI Tracker to scan paragraphs for metrics

TASK 3 — Create comprehensive unit tests tests/unit/test_financial_normalizer.py:
Test normalize_value with at least 25 cases covering:
- "$1.23B" → 1230.0 USD_millions
- "$1,234.5 million" → 1234.5 USD_millions  
- "1.23 billion" → 1230.0 USD_millions
- "(452)" → 452.0 USD_millions, is_negative=True
- "(1.2B)" → 1200.0 USD_millions, is_negative=True
- "12.3%" → 12.3 percentage
- "4.5M shares" → 4500000 count (not millions of USD)
- "$1,234" (in thousands context) → 1.234 USD_millions
- "—" → NaN, confidence=0.0
- "n/m" → NaN, confidence=0.0
- "€1.5B" → 1500.0 EUR_millions
- "£2.1B" → 2100.0 GBP_millions

Test normalize_period with at least 15 cases:
- "fiscal year 2024" → FY2024, annual
- "FY2024" → FY2024, annual
- "FY'24" → FY2024, annual
- "year ended December 31, 2024" → FY2024, annual
- "twelve months ended Dec 31, 2023" → FY2023, annual
- "Q1 2024" → Q1 2024, quarterly
- "first quarter 2024" → Q1 2024, quarterly
- "three months ended March 31, 2024" → Q1 2024, quarterly
- "Q3'24" → Q3 2024, quarterly

TASK 4 — Create tests/unit/test_table_extractor.py:
Use a synthetic PDF with a known 3-column table (create with reportlab):
1. Extracts the table and identifies column headers correctly
2. as_markdown produces valid pipe-delimited markdown
3. as_json has correct structure {"headers": [...], "rows": [...]}
4. caption is detected from text above the table

CONSTRAINTS:
- Docling is called synchronously (it doesn't have an async API); wrap in asyncio.to_thread() for use in async contexts
- The FinancialNormalizer must handle Unicode minus signs (−, U+2212) and en-dashes as negatives
- In-thousands vs in-millions context: the normalizer does NOT auto-detect context — the caller must pass context_unit="thousands" or "millions" if known from the document header
- normalize_value should never raise an exception — always return a NormalizedValue even if parsing fails (use confidence=0.0)

ACCEPTANCE CRITERIA:
1. All 25 normalize_value test cases pass
2. All 15 normalize_period test cases pass
3. TableExtractor.extract_tables() on the AAPL 10-K 2023 finds ≥10 tables (income statement, balance sheet, cash flow, etc.)
4. The income statement table as_json contains "Revenue" or "Net sales" as a row label
5. pytest tests/unit/test_financial_normalizer.py tests/unit/test_table_extractor.py -v → all green
```

---

## PROMPT 1.3 — Hierarchical Chunker, Embedding Pipeline & BM25 Sparse Index

```
You are implementing the core RAG indexing pipeline for the Stock Analyst AI platform.
The PDF parser, table extractor, and financial normalizer from previous steps are complete.
Working directory: packages/rag/
Qdrant is running at localhost:6333. Ollama is running at localhost:11434.

CONTEXT:
The chunking strategy is hierarchical (parent-child) to balance retrieval precision and context:
- Parent chunks (~2000 tokens): full document sections. Used for context when a child is retrieved.
- Child chunks (~200 tokens): paragraphs. These are what get embedded and searched.
- Table chunks: each extracted table stored as one chunk (JSON + markdown).
The Citation Enforcer will BM25-search for exact quotes to verify citations aren't hallucinated.
This requires BOTH dense embeddings (semantic search) AND sparse BM25 vectors (exact term matching)
to be stored in Qdrant as a hybrid index.

TASK 1 — Create packages/rag/ingestion/chunkers/hierarchical.py:

@dataclass
class Chunk:
    chunk_id: str               # UUID
    content: str                # The text content of this chunk
    chunk_type: str             # "parent", "child", "table"
    parent_chunk_id: str | None # None for parent chunks; parent's chunk_id for children
    metadata: dict              # Full metadata dict (see below)

Required metadata keys on every chunk:
{
    "document_id": str,
    "document_name": str,
    "filing_type": str,
    "period": str,
    "page_number": int,         # first page for multi-page parents
    "section_name": str,
    "chunk_type": str,
    "parent_chunk_id": str | None,
    "tenant_id": str,
    "coverage_id": str,
    "char_start": int,          # character offset in the full document text
    "char_end": int,
    "token_estimate": int,      # rough estimate: len(content.split()) * 1.3
}

class HierarchicalChunker:
    def __init__(self, parent_max_tokens: int = 2000, child_max_tokens: int = 200,
                 child_overlap_tokens: int = 20):
    
    def chunk_document(self, parsed_doc: ParsedDocument, 
                       tables: list[ExtractedTable],
                       tenant_id: str, coverage_id: str) -> list[Chunk]:
        # 1. Split parsed_doc into sections using parsed_doc.sections dict
        # 2. For each section: create parent chunk(s) — if section > parent_max_tokens, split further
        # 3. For each parent chunk: create child chunks (sliding window with overlap)
        # 4. For each ExtractedTable: create a table chunk with JSON + markdown as content
        # 5. Return all chunks (parents + children + tables) in reading order
        
    def _split_into_parent_chunks(self, section_name: str, text: str, 
                                   base_metadata: dict) -> list[Chunk]:
        # Split text on paragraph boundaries (double newlines)
        # Group paragraphs until approaching parent_max_tokens
        # Each group becomes one parent chunk
        
    def _split_into_child_chunks(self, parent: Chunk) -> list[Chunk]:
        # Split parent.content into ~child_max_tokens pieces
        # Use sentence boundaries (split on ". " or ".\n") to avoid mid-sentence cuts
        # Add child_overlap_tokens of overlap from previous child
        # Each child inherits all metadata from parent + adds parent_chunk_id
        
    def _create_table_chunk(self, table: ExtractedTable, 
                             base_metadata: dict) -> Chunk:
        # Content: f"TABLE: {table.caption or 'Untitled'}\n\n{table.as_markdown}\n\nJSON:\n{json.dumps(table.as_json)}"
        # chunk_type = "table"
        # page_number = table.page_number
        # section_name = table.section_name

TASK 2 — Create packages/rag/ingestion/pipeline.py — the embedding and indexing pipeline:

from qdrant_client import QdrantClient, models

class EmbeddingPipeline:
    def __init__(self, ollama_url: str, qdrant_client: QdrantClient, 
                 collection_prefix: str = "tenant"):
        self.ollama_url = ollama_url
        self.qdrant = qdrant_client
        self.model_name = "nomic-embed-text:v1.5"
        self.vector_dim = 768
        self.batch_size = 32
        
    async def ensure_collection(self, tenant_id: str) -> None:
        # Create Qdrant collection "tenant_{tenant_id}" if it doesn't exist
        # Collection config:
        #   vectors config: {"dense": VectorParams(size=768, distance=Distance.COSINE)}
        #   sparse vectors config: {"sparse": SparseVectorParams()} for BM25
        # If collection exists, do nothing (idempotent)
        
    async def embed_chunks(self, chunks: list[Chunk]) -> list[tuple[Chunk, list[float]]]:
        # Batch chunks in groups of self.batch_size
        # For each batch: POST to http://ollama:11434/api/embeddings
        #   {"model": "nomic-embed-text:v1.5", "prompt": chunk.content}
        # Note: Ollama embeddings API takes one prompt at a time; loop within batch
        # Return list of (chunk, embedding_vector) pairs
        
    def compute_bm25_sparse(self, text: str) -> dict[int, float]:
        # Tokenize text: lowercase, split on non-alphanumeric, remove stopwords
        # Compute TF-IDF style BM25 weights using rank_bm25
        # Return dict: {token_id: weight} where token_id = hash(token) % 30000
        # This creates a sparse vector representation for Qdrant
        
    async def index_chunks(self, chunks: list[Chunk], tenant_id: str) -> int:
        # 1. Ensure collection exists
        # 2. Filter to child chunks + table chunks only for embedding (parents stored but not embedded)
        #    Parents are stored as payload-only points for hydration
        # 3. Batch embed child + table chunks
        # 4. For each chunk: upsert to Qdrant with:
        #    - id: chunk.chunk_id (UUID)
        #    - vectors: {"dense": embedding, "sparse": bm25_sparse}
        #    - payload: chunk.metadata + {"content": chunk.content}
        # 5. For parent chunks: upsert as payload-only (no vector) for hydration
        # Return total points upserted

TASK 3 — Create packages/rag/connectors/qdrant_client.py:
A thin wrapper around the Qdrant client with retry logic and connection pooling:

class QdrantConnector:
    def __init__(self, host: str, port: int, timeout: float = 30.0)
    
    async def upsert_points(self, collection: str, points: list[PointStruct]) -> None:
        # Batch upsert with retry (up to 3 attempts, exponential backoff)
        
    async def search_dense(self, collection: str, query_vector: list[float],
                            filter_: dict, limit: int) -> list[ScoredPoint]:
        # Dense vector search with mandatory filter
        
    async def search_sparse(self, collection: str, sparse_vector: dict[int, float],
                             filter_: dict, limit: int) -> list[ScoredPoint]:
        # Sparse BM25 vector search with mandatory filter
        
    async def get_point(self, collection: str, point_id: str) -> Record | None:
        # Fetch a single point by ID (used for parent hydration)

TASK 4 — Create unit tests tests/unit/test_chunker.py:
Use a synthetic ParsedDocument with 3 sections (20 paragraphs each):
1. chunk_document() returns chunks with chunk_type in {"parent", "child", "table"}
2. Every child chunk has a valid parent_chunk_id pointing to an existing parent
3. Every chunk has all required metadata keys
4. Parent chunks have token_estimate ≤ 2200 (within tolerance of 2000 target)
5. Child chunks have token_estimate ≤ 240 (within tolerance of 200 target)
6. No chunk has empty content
7. Table chunks content starts with "TABLE:"
8. Total child chunks > total parent chunks (many children per parent)

CONSTRAINTS:
- Ollama's embedding API is synchronous-style HTTP; wrap in asyncio.to_thread for true async
- BM25 sparse vectors: use a fixed vocabulary hash space of 30000 to keep sparse vectors manageable
- Never index parent chunks as searchable vectors — only as payload-only points for hydration
- The collection name must always be "tenant_{tenant_id}" — never use a shared collection
- Upsert should use Qdrant's batch upsert (max 100 points per call) to avoid payload size limits

ACCEPTANCE CRITERIA:
1. chunk_document() on the AAPL 10-K (from PDF parser) produces >500 child chunks
2. All child chunks have all 12 required metadata keys populated
3. embed_chunks() embeds 100 chunks via Ollama in <15 seconds
4. index_chunks() indexes 500 child chunks into Qdrant; verify with Qdrant count endpoint
5. BM25 sparse search for "revenue increased" finds the correct paragraph in top-3 results
6. All unit tests in test_chunker.py pass
```

---

## PROMPT 1.4 — Hybrid Retriever & Ingestion API

```
You are implementing the retrieval layer and the document management API for the Stock Analyst AI platform.
The chunker, embedding pipeline, and Qdrant connector from the previous step are complete.
Working directory: packages/rag/ and apps/api/

CONTEXT:
The HybridRetriever is the most security-critical component in the retrieval layer. It MUST always
apply tenant_id and coverage_id filters — without them, cross-tenant data leakage is possible.
The two-stage retrieval (dense + sparse → RRF fusion → reranking → parent hydration) is what
enables the Citation Enforcer to verify exact quotes: BM25 finds the exact phrase, dense finds
the semantic context, reranking selects the most relevant, parent hydration gives full section context.

TASK 1 — Create packages/rag/retrieval/hybrid_retriever.py:

@dataclass
class RetrievedChunk:
    chunk_id: str
    content: str
    metadata: dict
    score: float
    parent_content: str | None  # hydrated parent section text
    parent_chunk_id: str | None

class HybridRetriever:
    def __init__(self, qdrant: QdrantConnector, embedding_pipeline: EmbeddingPipeline,
                 reranker_model: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
        self.qdrant = qdrant
        self.embedder = embedding_pipeline
        # Load reranker: from sentence_transformers import CrossEncoder
        # self.reranker = CrossEncoder(reranker_model)
        
    async def retrieve(self, query: str, tenant_id: str, coverage_id: str,
                       top_k: int = 20, rerank_top_n: int = 8,
                       filters: dict | None = None) -> list[RetrievedChunk]:
        # MANDATORY: always include tenant_id and coverage_id in filter
        # Never allow retrieval without both of these
        
        base_filter = {
            "must": [
                {"key": "tenant_id", "match": {"value": tenant_id}},
                {"key": "coverage_id", "match": {"value": coverage_id}},
                {"key": "chunk_type", "match": {"any": ["child", "table"]}}
            ]
        }
        if filters:
            base_filter["must"].extend(filters.get("must", []))
        
        # Stage 1A: Dense retrieval
        query_embedding = await self.embedder.embed_single(query)
        dense_results = await self.qdrant.search_dense(
            collection=f"tenant_{tenant_id}",
            query_vector=query_embedding,
            filter_=base_filter,
            limit=top_k
        )
        
        # Stage 1B: Sparse BM25 retrieval
        sparse_vec = self.embedder.compute_bm25_sparse(query)
        sparse_results = await self.qdrant.search_sparse(
            collection=f"tenant_{tenant_id}",
            sparse_vector=sparse_vec,
            filter_=base_filter,
            limit=top_k
        )
        
        # Stage 1C: Reciprocal Rank Fusion
        candidates = self._reciprocal_rank_fusion(dense_results, sparse_results)
        
        # Stage 2: CrossEncoder reranking
        reranked = await asyncio.to_thread(self._rerank, query, candidates, rerank_top_n)
        
        # Stage 3: Parent hydration
        hydrated = await self._hydrate_parents(reranked, tenant_id)
        
        return hydrated
        
    def _reciprocal_rank_fusion(self, dense: list, sparse: list, k: int = 60) -> list:
        # Standard RRF: score = sum(1 / (k + rank)) across result lists
        # Deduplicate by chunk_id, taking best combined score
        # Return sorted by combined RRF score descending
        
    def _rerank(self, query: str, candidates: list, top_n: int) -> list:
        # Use CrossEncoder to score (query, chunk_content) pairs
        # Return top_n chunks by reranker score
        
    async def _hydrate_parents(self, chunks: list, tenant_id: str) -> list[RetrievedChunk]:
        # For each chunk: if it has a parent_chunk_id, fetch the parent's content from Qdrant
        # Add parent_content to the RetrievedChunk
        # Parent gives the LLM broader context around the cited paragraph
        
    async def retrieve_exact_quote(self, quote: str, tenant_id: str, 
                                    coverage_id: str) -> RetrievedChunk | None:
        # Used by Citation Enforcer to verify quotes
        # BM25-only search for the exact phrase
        # Returns the chunk if found with score > threshold, else None
        # This is a security check — must enforce tenant + coverage filter

TASK 2 — Create packages/rag/retrieval/reranker.py:
Separate module to allow lazy loading of the CrossEncoder model:

class Reranker:
    _model = None  # class-level lazy singleton
    
    @classmethod
    def get_model(cls) -> CrossEncoder:
        if cls._model is None:
            from sentence_transformers import CrossEncoder
            cls._model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return cls._model
    
    def rerank(self, query: str, chunks: list[dict], top_n: int) -> list[dict]:
        model = self.get_model()
        pairs = [(query, c["content"]) for c in chunks]
        scores = model.predict(pairs)
        scored = sorted(zip(chunks, scores), key=lambda x: x[1], reverse=True)
        return [c for c, _ in scored[:top_n]]

TASK 3 — Implement Celery ingestion task at apps/api/tasks/ingestion.py:

from celery import Celery
celery_app = Celery("stockanalyst", broker=settings.REDIS_URL, backend=settings.REDIS_URL)

@celery_app.task(bind=True, max_retries=3, default_retry_delay=30)
def ingest_document_task(self, document_id: str, coverage_id: str, tenant_id: str):
    # Run the full ingestion pipeline synchronously (Celery workers are sync):
    # 1. Load document record from PostgreSQL (get storage_path, file_name, filing_type, period)
    # 2. Download raw file from MinIO to a temp file
    # 3. SHA-256 hash check: if hash already in any document for this coverage → mark duplicate, return
    # 4. PDFParser().parse(temp_path, document_id, file_name)
    # 5. TableExtractor().extract_tables(temp_path, parsed_doc, document_id, filing_type, period)
    # 6. If overall_text_coverage < 0.5: update document ingest_status="review_needed", return
    # 7. HierarchicalChunker().chunk_document(parsed_doc, tables, tenant_id, coverage_id)
    # 8. EmbeddingPipeline().index_chunks(chunks, tenant_id)  — sync wrapper using asyncio.run()
    # 9. Update document in PostgreSQL: chunk_count, quality_score, ingest_status="indexed", ingested_at=now()
    # 10. Update coverage: document_count += 1, last_updated = now()
    # 11. Append to agent_audit_log: agent_name="DocumentIngestionAgent", action="ingest_complete"
    # On any exception: self.retry(exc=e); after max retries: update ingest_status="failed"

TASK 4 — Implement document REST endpoints at apps/api/routers/documents.py:
Replace the 501 stubs with real implementations.

POST /api/v1/coverages/{coverage_id}/documents:
  Request body (multipart or JSON):
    Option A (file upload): multipart with file field + form fields: filing_type, period, source
    Option B (SEC fetch): JSON body: {"ticker": "AAPL", "form_type": "10-K", "year": 2023}
  Processing:
    - Verify coverage_id belongs to current_user.tenant_id (RLS handles DB, but verify at API level too)
    - Option A: save file to MinIO, create document record, enqueue ingest_document_task
    - Option B: call SECEdgarConnector.fetch_filing(), create document record, enqueue ingest_document_task
  Response: 202 Accepted with {"document_id": "...", "task_id": "...", "status": "queued"}

GET /api/v1/coverages/{coverage_id}/documents:
  Returns list of documents with: id, file_name, filing_type, period, ingest_status, 
  chunk_count, quality_score, ingested_at
  Filter by: ingest_status (query param)

DELETE /api/v1/coverages/{coverage_id}/documents/{document_id}:
  - Delete all Qdrant points with filter: document_id = document_id AND tenant_id = tenant_id
  - Delete file from MinIO
  - Delete document record from PostgreSQL (CASCADE removes related data)
  - Update coverage.document_count -= 1
  Response: 204 No Content

GET /api/v1/tasks/{task_id}:
  Returns task status from task_queue table: status, started_at, completed_at, error

TASK 5 — Integration test tests/integration/test_retriever.py:
Prerequisites: real Qdrant running, AAPL 10-K already indexed (use a test fixture that runs ingestion)
1. retrieve("gross margin trend", tenant_a_id, aapl_coverage_id) returns 8 chunks
2. All returned chunks have chunk_type in ["child", "table"]
3. All returned chunks have metadata.tenant_id == tenant_a_id
4. retrieve with tenant_b_id and aapl_coverage_id (which belongs to tenant_a) returns [] (zero results)
5. retrieve_exact_quote("revenue increased 8%", ...) — if this phrase is in the filing, returns the chunk
6. Latency: retrieve() completes in <500ms (time 10 calls, check p95)

CONSTRAINTS:
- HybridRetriever.retrieve() must raise ValueError if tenant_id or coverage_id is None or empty
- The base_filter MUST be applied to BOTH dense and sparse searches — never skip it
- CrossEncoder model loading is slow (~2s); load it at worker startup, not per-request
- Celery task must use asyncio.run() to call async pipeline code from a sync task
- The POST /documents endpoint must enforce a file size limit: reject files > 100MB

ACCEPTANCE CRITERIA:
1. POST /coverages/{id}/documents with an AAPL 10-K PDF → 202 response with task_id
2. Celery worker picks up the task and completes within 120 seconds
3. GET /coverages/{id}/documents shows the document as "indexed" with chunk_count > 0
4. HybridRetriever.retrieve() returns 8 results for a semantic query
5. Integration test: cross-tenant retrieval returns zero results
6. Integration test: p95 retrieval latency < 500ms
```

---

## PROMPT 1.5 — Document Management UI (Next.js)

```
You are implementing the document management UI for the Stock Analyst AI platform.
The document REST API from the previous step is complete and running at localhost:8000.
Working directory: apps/web/

CONTEXT:
Analysts need to see all documents for a coverage, upload new ones, trigger SEC auto-fetch,
monitor ingestion progress in real-time (polling task status), and spot quality issues.
The UI uses Next.js 14 App Router, shadcn/ui components, and TanStack Query for data fetching.

TASK 1 — Create Coverage list page: apps/web/app/(protected)/coverages/page.tsx
This is a server component that fetches the list of coverages for the logged-in tenant.
Display as a grid of cards (shadcn Card component), each showing:
- Ticker badge (large, monospace font) + Company name
- Industry name (grey subtitle)
- Document count chip
- Status badge (setup/active/archived with color coding: setup=yellow, active=green, archived=grey)
- Last updated date (relative: "2 days ago")
- "Open" button linking to /coverages/{id}

Include a "New Coverage" button that opens a modal (sheet from shadcn).
New Coverage modal:
- Ticker input (uppercase enforced)
- Company name input
- Exchange select: NYSE, NASDAQ, LSE, TSX, ASX, Other
- Industry select (fetched from GET /industries)
- Submit → POST /coverages → redirect to /coverages/{id}/documents

TASK 2 — Create Coverage detail layout: apps/web/app/(protected)/coverages/[id]/layout.tsx
Sub-navigation tabs for a coverage:
- Documents (default tab)
- Research (dropdown: Industry, Bull Case, Bear Case, Quarterly)
- KPIs
- Notes

Each tab navigates to a sub-route. Active tab highlighted.
Coverage header: shows ticker + company name + status badge + last-updated.
Fetch coverage details server-side and pass as props.

TASK 3 — Create Document list page: apps/web/app/(protected)/coverages/[id]/documents/page.tsx
Client component (uses TanStack Query for polling).

Layout:
- Action bar at top: "Upload Document" button + "Fetch from SEC EDGAR" button
- Table of documents with columns:
  | File Name | Type | Period | Status | Chunks | Quality | Ingested | Actions |
  
Status badge component:
- "Indexing" → yellow spinner badge
- "Indexed" → green check badge  
- "Failed" → red × badge with retry button
- "Review Needed" → orange warning badge with tooltip: "Text extraction < 50%. Manual review recommended."
- "Queued" → grey clock badge

Quality score visualization:
- ≥ 0.8: green progress bar
- 0.5–0.8: yellow progress bar
- < 0.5: red progress bar with warning icon

Polling behavior:
- While any document has status "Indexing" or "Queued": refetch every 3 seconds (TanStack Query refetchInterval)
- When all documents are "Indexed", "Failed", or "Review Needed": stop polling

TASK 4 — Create Upload Document modal: apps/web/components/documents/upload-modal.tsx
Two-tab modal:
Tab 1 "Upload File":
  - Drag-and-drop zone (react-dropzone)
  - Accepts: PDF only, max 100MB
  - Fields: Filing Type select (10-K, 10-Q, 8-K, Earnings Transcript, Investor Day, Custom)
  - Period input: "FY2024" or "Q3 2024" (with example placeholder)
  - Upload progress bar (using XHR with progress event, not fetch)
  - On success: close modal, show toast "Document queued for indexing"

Tab 2 "Fetch from SEC EDGAR":
  - Ticker input (pre-filled from coverage ticker)
  - Filing Type select: 10-K, 10-Q, 8-K
  - Year input: number (last 5 years as options in a select)
  - "Fetch" button → POST /coverages/{id}/documents with JSON body
  - Loading state: "Fetching from SEC EDGAR..." with spinner
  - On success: close modal, show toast "Filing fetched and queued for indexing"

TASK 5 — Create Delete confirmation dialog: apps/web/components/documents/delete-document-dialog.tsx
- shadcn AlertDialog
- Message: "Delete {file_name}? This will remove {chunk_count} indexed chunks and cannot be undone."
- On confirm: DELETE /coverages/{id}/documents/{doc_id} → invalidate TanStack Query cache → row disappears
- Disable confirm button if document status is "Indexing"

TASK 6 — Create apps/web/lib/queries/documents.ts:
TanStack Query hooks:
- useDocuments(coverageId): GET /coverages/{id}/documents, refetchInterval logic
- useUploadDocument(coverageId): mutation for file upload
- useFetchFromSEC(coverageId): mutation for SEC auto-fetch
- useDeleteDocument(coverageId): mutation with optimistic removal from list
- useTaskStatus(taskId): GET /tasks/{taskId}, polls every 2 seconds until terminal status

CONSTRAINTS:
- The upload uses XHR (not fetch) to support upload progress tracking
- Polling must stop when there are no in-progress documents — use a computed refetchInterval returning false to disable
- All mutations must invalidate the documents query cache on success so the list refreshes
- Quality score bar must never show NaN or undefined — handle null quality_score gracefully (show "Pending")
- The Coverage list page is a Server Component; the Documents page is a Client Component

ACCEPTANCE CRITERIA:
1. /coverages shows all coverages for the logged-in tenant with correct status badges
2. "New Coverage" modal creates a coverage and redirects to /coverages/{id}/documents
3. "Fetch from SEC EDGAR" fetches AAPL 10-K 2023 → document appears as "Queued" then transitions to "Indexing" then "Indexed" without page refresh
4. Quality score bar renders correctly for scores 0.3, 0.6, 0.9
5. Delete confirmation dialog warns about chunk count and completes deletion
6. "Review Needed" badge shows tooltip on hover with the explanation text
```
