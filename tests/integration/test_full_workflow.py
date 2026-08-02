"""Integration test: full happy path from document upload through an
approved Lynch Pitch.

Prerequisites (see tests/integration/test_auth.py and test_kpi_tracker.py for
the same convention):
  - Full Docker Compose stack running (Postgres, Redis, Qdrant, MinIO,
    Keycloak, Ollama, LiteLLM) -- `make up`
  - DB migrated:            alembic upgrade head
  - Dev data seeded:        python scripts/seed_dev.py
  - API running:            uvicorn apps.api.main:app
  - A Celery worker running against the shared "stockanalyst" app, e.g.:
        celery -A apps.api.tasks.scheduler worker --loglevel=info
    (both document ingestion and agent-task dispatch need it -- see
    apps/api/celery_config.py's module docstring for why any of
    apps.api.tasks.scheduler / apps.api.tasks.ingestion /
    agents.orchestrator.tasks register tasks visible to the others)
  - LITELLM_URL reachable with real ANTHROPIC_API_KEY/OPENAI_API_KEY configured
    -- the Lynch Pitch agent's LLM call is NOT mocked here. This is an
    end-to-end quality gate exercising the real model, not a unit test.

Run:
    pytest tests/integration/test_full_workflow.py -v -m integration
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from shared.models import Coverage
from sqlalchemy import select

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# A small synthetic eval fixture (a few KB, shaped like a 10-K -- see
# eval/fixtures/fixture_content.py) rather than a real filing; there is no
# `msft_10k_2023_abridged.pdf` in the repo, so a document is uploaded under a
# freshly created MSFT coverage instead of relying on the ticker matching the
# fixture's own AAPL-branded content, which the ingestion pipeline never checks.
_FIXTURE_PDF = (
    Path(__file__).resolve().parents[2] / "eval" / "fixtures" / "documents" / "aapl_10k_2023.pdf"
)

_POLL_INTERVAL_SECONDS = 2.0
_INGEST_TIMEOUT_SECONDS = 120.0
_AGENT_TIMEOUT_SECONDS = 120.0


async def _poll_task(api_client: httpx.AsyncClient, task_id: str, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while True:
        resp = await api_client.get(f"/tasks/{task_id}")
        resp.raise_for_status()
        task: dict[str, Any] = resp.json()
        if task["status"] in ("completed", "failed", "cancelled"):
            return task
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"task {task_id} did not finish within {timeout_seconds}s (last status: {task['status']})"
            )
        await asyncio.sleep(_POLL_INTERVAL_SECONDS)


async def test_full_coverage_workflow(api_client: httpx.AsyncClient, db_session: Any) -> None:
    # Step 1: create a coverage under tenant A
    resp = await api_client.post(
        "/coverages",
        json={"ticker": "MSFT", "company_name": "Microsoft Corporation", "exchange": "NASDAQ"},
    )
    assert resp.status_code == 201, resp.text
    coverage_id = resp.json()["id"]

    # Step 2: upload a 10-K
    assert _FIXTURE_PDF.exists(), f"missing eval fixture: {_FIXTURE_PDF}"
    with _FIXTURE_PDF.open("rb") as fh:
        resp = await api_client.post(
            f"/coverages/{coverage_id}/documents",
            files={"file": (_FIXTURE_PDF.name, fh, "application/pdf")},
            data={"filing_type": "10-K", "period": "FY2023", "source": "user_upload"},
        )
    assert resp.status_code == 202, resp.text
    ingest_task_id = resp.json()["task_id"]

    # Step 3: wait for ingestion to complete
    ingest_task = await _poll_task(api_client, ingest_task_id, _INGEST_TIMEOUT_SECONDS)
    assert ingest_task["status"] == "completed", (
        f"ingestion did not complete within {_INGEST_TIMEOUT_SECONDS}s: {ingest_task}"
    )

    # Step 4: verify the document landed in Qdrant with real chunks
    doc_resp = await api_client.get(f"/coverages/{coverage_id}/documents")
    assert doc_resp.status_code == 200
    docs = doc_resp.json()
    assert len(docs) == 1
    doc = docs[0]
    assert doc["ingest_status"] == "indexed"
    # eval/fixtures/documents/*.pdf are a few KB of synthetic text, not a real
    # filing, so this only asserts *some* chunks were produced -- a
    # production-scale ">100 chunks" threshold doesn't apply to this fixture.
    assert doc["chunk_count"] > 0, "expected at least one indexed chunk"

    # Step 5: run the Lynch Pitch agent
    pitch_resp = await api_client.post(
        f"/coverages/{coverage_id}/tasks/lynch_pitch", json={"skill": "default", "payload": {}}
    )
    assert pitch_resp.status_code == 202, pitch_resp.text
    pitch_task_id = pitch_resp.json()["task_id"]

    # Step 6: wait for the Lynch Pitch task
    pitch_task = await _poll_task(api_client, pitch_task_id, _AGENT_TIMEOUT_SECONDS)
    assert pitch_task["status"] == "completed", f"lynch_pitch task failed: {pitch_task.get('error')}"

    # Step 7: verify the approved output landed in research_outputs
    outputs_resp = await api_client.get(f"/coverages/{coverage_id}/outputs")
    assert outputs_resp.status_code == 200
    lynch_outputs = [o for o in outputs_resp.json() if o["output_type"] == "lynch_pitch"]
    assert len(lynch_outputs) == 1
    output = lynch_outputs[0]
    assert output["approved_by_enforcer"] is True
    assert output["citation_coverage_pct"] >= 0.95
    assert output["enforcer_status"] == "approved"

    # Step 8: all 8 Lynch questions answered
    content = output["content"]
    for q_num in range(1, 9):
        assert f"### Q{q_num}:" in content, f"Q{q_num} header missing from output"

    # Cross-check against Postgres directly (RLS-scoped to tenant A by db_session)
    coverage_row = (
        await db_session.execute(select(Coverage).where(Coverage.id == uuid.UUID(coverage_id)))
    ).scalar_one()
    assert coverage_row.document_count == 1
