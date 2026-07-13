# ──────────────────────────────────────────────────────────────────────────────
# Stock Analyst AI — Developer Makefile
#
# Prerequisites: GNU Make, Docker w/ Compose plugin, Python ≥3.12, Node ≥20
# Linux/macOS: works as-is.
# Windows: use Git Bash or WSL. PowerShell users must set PYTHONPATH manually.
# ──────────────────────────────────────────────────────────────────────────────

COMPOSE    := docker compose -f infra/docker-compose.yml
PYTHON     := python
API_MODULE := apps.api.main:app

.PHONY: up down logs migrate seed test lint dev-api dev-web pull-model

# ── Docker Compose ────────────────────────────────────────────────────────────

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f

# ── Database ──────────────────────────────────────────────────────────────────

migrate:
	alembic upgrade head

# ── Data seeding ──────────────────────────────────────────────────────────────

seed:
	$(PYTHON) scripts/seed_dev.py && $(PYTHON) scripts/setup_minio.py

# ── Tests ─────────────────────────────────────────────────────────────────────

test:
	pytest tests/unit/ --cov=apps/api/services --cov-fail-under=80 -v

# ── Linting ───────────────────────────────────────────────────────────────────

lint:
	ruff check packages/ apps/api/ && \
	ruff format --check packages/ apps/api/ && \
	mypy --ignore-missing-imports --strict packages/ apps/api/

# ── Local development ─────────────────────────────────────────────────────────

dev-api:
	PYTHONPATH=. uvicorn $(API_MODULE) --reload --host 0.0.0.0 --port 8000

dev-web:
	(cd apps/web && npm run dev)

# ── Ollama model ──────────────────────────────────────────────────────────────

pull-model:
	$(COMPOSE) exec ollama ollama pull nomic-embed-text:v1.5
