"""Load test for the read-heavy analyst workflows (NFR-PERF gate).

Auth is real Keycloak, not a stubbed token endpoint -- this app has no
`/api/auth/token`; JWTs come from Keycloak's password grant, same as
tests/conftest.py's `_password_grant_token`. The login call itself runs
through a plain httpx request in `on_start`, deliberately *not* through
`self.client`, so it never pollutes the recorded task latencies.

Requires a coverage that already has at least one indexed document (search/
KPI/output endpoints against an empty coverage would only measure empty-list
latency, not realistic query cost) -- point LOAD_TEST_COVERAGE_ID at one,
e.g. a coverage seeded via `python scripts/seed_dev.py` or the eval fixture
coverages built by `python -m eval.fixtures.setup_fixtures`.

Run:
    LOAD_TEST_COVERAGE_ID=<uuid> locust -f tests/load/locustfile.py \\
        --headless -u 10 -r 2 --run-time 5m --host http://localhost:8000

Target (NFR-PERF): p95 < 500ms across all tasks, 0% error rate.
"""
from __future__ import annotations

import os

import httpx
from locust import HttpUser, between, events, task

KEYCLOAK_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.environ.get("KEYCLOAK_REALM", "stock-analyst")
KEYCLOAK_CLIENT_ID = os.environ.get("KEYCLOAK_CLIENT_ID", "stock-analyst-api")
KEYCLOAK_CLIENT_SECRET = os.environ.get("KEYCLOAK_CLIENT_SECRET", "changeme")

LOAD_TEST_USERNAME = os.environ.get("LOAD_TEST_USERNAME", "analyst-a")
LOAD_TEST_PASSWORD = os.environ.get("LOAD_TEST_PASSWORD", "TestPass123!")
LOAD_TEST_COVERAGE_ID = os.environ.get("LOAD_TEST_COVERAGE_ID")


@events.test_start.add_listener
def _require_coverage_id(environment, **kwargs) -> None:
    if not LOAD_TEST_COVERAGE_ID:
        raise RuntimeError(
            "Set LOAD_TEST_COVERAGE_ID to a coverage UUID that already has at "
            "least one indexed document before running locust against this file "
            "-- see this module's docstring."
        )


class AnalystUser(HttpUser):
    wait_time = between(1, 5)

    def on_start(self) -> None:
        token_url = f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token"
        resp = httpx.post(
            token_url,
            data={
                "grant_type": "password",
                "client_id": KEYCLOAK_CLIENT_ID,
                "client_secret": KEYCLOAK_CLIENT_SECRET,
                "username": LOAD_TEST_USERNAME,
                "password": LOAD_TEST_PASSWORD,
            },
            timeout=10,
        )
        resp.raise_for_status()
        access_token = resp.json()["access_token"]
        self.client.headers["Authorization"] = f"Bearer {access_token}"
        self.coverage_id = LOAD_TEST_COVERAGE_ID

    @task(3)
    def list_coverages(self) -> None:
        self.client.get("/coverages", name="/coverages")

    @task(3)
    def list_documents(self) -> None:
        self.client.get(f"/coverages/{self.coverage_id}/documents", name="/coverages/[id]/documents")

    @task(2)
    def search_coverage(self) -> None:
        self.client.get(
            f"/coverages/{self.coverage_id}/search",
            params={"q": "gross margin revenue growth"},
            name="/coverages/[id]/search",
        )

    @task(1)
    def view_kpis(self) -> None:
        self.client.get(f"/coverages/{self.coverage_id}/kpis", name="/coverages/[id]/kpis")

    @task(1)
    def view_outputs(self) -> None:
        self.client.get(f"/coverages/{self.coverage_id}/outputs", name="/coverages/[id]/outputs")
