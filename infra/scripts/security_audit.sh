#!/bin/bash
# infra/scripts/security_audit.sh — automated pre-deployment security audit
# for the Stock Analyst AI platform. Intended as a CI gate: exits 1 if any
# check marked FAIL fails. WARN checks are surfaced but never gate CI —
# they cover things this repo can't fully control (Traefik's static config)
# or hygiene items that don't represent an active vulnerability on their own.
#
# Every check below is grounded in the actual current implementation:
#   - apps/api/routers/coverages.py returns 404 (not 403) for a coverage the
#     caller's tenant doesn't own — RLS-filtered rows read as "not found",
#     which is deliberate (it doesn't confirm the row exists for tenant B).
#   - migrations/versions/001_initial_schema.py enables RLS with
#     `USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid)`
#     and REVOKEs DELETE/UPDATE on agent_audit_log FROM PUBLIC.
#   - packages/agents/src/agents/industry_analyst/tools.py's fetch_url()
#     raises ValueError("Domain not in allowlist: ...") for SSRF-y targets.
#   - Qdrant collections are per-tenant (tenant_{tenant_id}) AND filtered by
#     coverage_id (packages/rag/src/rag/retrieval/hybrid_retriever.py) —
#     genuine defense in depth, not just an API-layer check.
#
# KNOWN GAPS this script will legitimately FAIL on until fixed (not bugs in
# the script — see the audit-log-immutability check below for detail):
#   - POSTGRES_USER (as provisioned by the stock postgres:16 Docker image
#     entrypoint) is a Postgres SUPERUSER. Superusers bypass RLS and ignore
#     GRANT/REVOKE entirely, so as long as the API/Celery connect using
#     POSTGRES_USER, both the RLS check and the audit-log-immutability check
#     below are auditing a boundary the app's own connection can walk
#     straight through. The real fix is a dedicated, non-superuser
#     `stockanalyst_app` role (NOSUPERUSER, and NOT the owner of these
#     tables, so RLS applies to it) that the application connects as, with
#     POSTGRES_USER reserved for running migrations. That's a schema +
#     credential change beyond this script's scope — tracked as a follow-up,
#     not silently patched here.
#
# Required env vars (see the `: "${VAR:?...}"` preflight below for the
# authoritative list) — this script does not create test fixtures; point it
# at tenants/coverages/tokens already seeded by scripts/seed_dev.py or your
# own staging fixtures.
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

: "${API_URL:?API_URL is required, e.g. https://api.stock-analyst.internal}"
: "${TENANT_A_JWT:?TENANT_A_JWT is required — a valid Keycloak access token for a tenant-A user}"
: "${TENANT_B_COVERAGE_ID:?TENANT_B_COVERAGE_ID is required — a coverage id owned by tenant B}"
: "${TENANT_A_ID:?TENANT_A_ID is required — tenant A's UUID}"
: "${TENANT_B_ID:?TENANT_B_ID is required — tenant B's UUID}"
: "${TEST_COVERAGE_ID:?TEST_COVERAGE_ID is required — a coverage id owned by the tenant behind TENANT_A_JWT}"
: "${PGHOST:?PGHOST is required (psql connection env — PGPORT/PGDATABASE/PGUSER/PGPASSWORD too)}"
LOKI_URL="${LOKI_URL:-http://loki.stock-analyst-obs.svc:3100}"

PASS=0
FAIL=0
WARN=0
declare -a FAILED_NAMES=()
declare -a WARNED_NAMES=()

pass() { echo "  PASS: $1"; PASS=$((PASS + 1)); }
fail() {
  echo "  FAIL: $1"
  [ -n "${2:-}" ] && echo "        $2"
  FAIL=$((FAIL + 1))
  FAILED_NAMES+=("$1")
}
warn() {
  echo "  WARN: $1"
  [ -n "${2:-}" ] && echo "        $2"
  WARN=$((WARN + 1))
  WARNED_NAMES+=("$1")
}

need() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required tool '$1' not found on PATH" >&2
    exit 2
  }
}
for tool in curl psql kubectl jq python3; do need "$tool"; done

echo "=== Stock Analyst AI Security Audit ==="
echo "API_URL=$API_URL"

# ── A01: Broken Access Control ───────────────────────────────────────────────
echo "--- A01: Access Control ---"

code=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TENANT_A_JWT" \
  "$API_URL/coverages/$TENANT_B_COVERAGE_ID")
if [[ "$code" == "403" || "$code" == "404" ]]; then
  pass "cross-tenant API access blocked (got $code)"
else
  fail "cross-tenant API access blocked" "expected 403/404, got $code"
fi

rls_count=$(PGPASSWORD="${PGPASSWORD:-}" psql -h "$PGHOST" -p "${PGPORT:-5432}" \
  -U "${PGUSER:-stockanalyst}" -d "${PGDATABASE:-stockanalyst}" -tA \
  -c "SET app.current_tenant_id = '${TENANT_A_ID}'; SELECT count(*) FROM coverages WHERE tenant_id = '${TENANT_B_ID}';" \
  2>/dev/null | tail -1 | tr -d '[:space:]')
if [[ "$rls_count" == "0" ]]; then
  pass "RLS enforced in PostgreSQL (tenant A sees 0 of tenant B's coverages)"
else
  fail "RLS enforced in PostgreSQL" \
    "expected 0 rows, got '$rls_count' — see the superuser caveat in this script's header comment"
fi

qdrant_leak=$(python3 -c "
import asyncio, sys
sys.path.insert(0, '$REPO_ROOT/packages/agents/src')
sys.path.insert(0, '$REPO_ROOT/packages/rag/src')
sys.path.insert(0, '$REPO_ROOT/packages/shared/src')
from agents.orchestrator.graph import get_retriever

async def main():
    retriever = get_retriever()
    results = await retriever.retrieve(
        query='test query for tenant isolation audit',
        tenant_id='$TENANT_A_ID',
        coverage_id='$TENANT_B_COVERAGE_ID',
        rerank_top_n=5,
    )
    print(len(results))

asyncio.run(main())
" 2>/dev/null | tail -1)
if [[ "$qdrant_leak" == "0" ]]; then
  pass "Qdrant tenant isolation (0 cross-tenant results)"
else
  fail "Qdrant tenant isolation" "expected 0 results, got '$qdrant_leak'"
fi

# ── A02: Cryptographic Failures ──────────────────────────────────────────────
echo "--- A02: Cryptographic Failures ---"

tls_code=$(curl -s -o /dev/null -w "%{http_code}" "http://${API_URL#https://}/health")
if [[ "$tls_code" == "301" || "$tls_code" == "308" ]]; then
  pass "plain-HTTP requests redirected to HTTPS (got $tls_code)"
else
  warn "plain-HTTP requests redirected to HTTPS" \
    "got $tls_code, expected 301/308 — this is Traefik's static entrypoints config (its own Helm release, not this repo); see infra/helm/stock-analyst-infra/templates/traefik/ingressroute.yaml's header comment"
fi

hardcoded=$(kubectl get pods -n stock-analyst -o json 2>/dev/null | jq -r '
  .items[].spec.containers[].env[]?
  | select(.value != null)
  | select(.name | test("API_KEY|PASSWORD|SECRET|TOKEN$"))
  | .name')
if [[ -z "$hardcoded" ]]; then
  pass "no credential-shaped env vars set via a literal value (all use secretKeyRef)"
else
  fail "no credential-shaped env vars set via a literal value" \
    "found: $(echo "$hardcoded" | tr '\n' ' ')"
fi

# ── A03: Injection ────────────────────────────────────────────────────────────
echo "--- A03: Injection ---"

sqli_payload="'; DROP TABLE coverages; --"
sqli_code=$(curl -s -o /tmp/audit_sqli_resp.json -w "%{http_code}" -G \
  -H "Authorization: Bearer $TENANT_A_JWT" \
  --data-urlencode "q=$sqli_payload" \
  "$API_URL/coverages/$TEST_COVERAGE_ID/search")
if [[ "$sqli_code" == "200" ]] && jq -e 'type == "array"' /tmp/audit_sqli_resp.json >/dev/null 2>&1; then
  pass "SQL-injection-shaped query handled safely (200, valid JSON array)"
else
  fail "SQL-injection-shaped query handled safely" \
    "expected 200 + JSON array, got HTTP $sqli_code, body: $(cat /tmp/audit_sqli_resp.json 2>/dev/null)"
fi
rm -f /tmp/audit_sqli_resp.json

# ── A04: Audit log immutability ──────────────────────────────────────────────
echo "--- A04: Audit log immutability ---"

delete_err=$(PGPASSWORD="${PGPASSWORD:-}" psql -h "$PGHOST" -p "${PGPORT:-5432}" \
  -U "${PGUSER:-stockanalyst}" -d "${PGDATABASE:-stockanalyst}" \
  -c "DELETE FROM agent_audit_log WHERE id = (SELECT id FROM agent_audit_log LIMIT 1);" 2>&1 || true)
if echo "$delete_err" | grep -qiE "error|permission denied"; then
  pass "audit log DELETE blocked"
else
  fail "audit log DELETE blocked" \
    "DELETE did not error — if PGUSER is a Postgres superuser, REVOKE has no effect (see header comment)"
fi

update_err=$(PGPASSWORD="${PGPASSWORD:-}" psql -h "$PGHOST" -p "${PGPORT:-5432}" \
  -U "${PGUSER:-stockanalyst}" -d "${PGDATABASE:-stockanalyst}" \
  -c "UPDATE agent_audit_log SET action = 'modified' WHERE id = (SELECT id FROM agent_audit_log LIMIT 1);" 2>&1 || true)
if echo "$update_err" | grep -qiE "error|permission denied"; then
  pass "audit log UPDATE blocked"
else
  fail "audit log UPDATE blocked" \
    "UPDATE did not error — if PGUSER is a Postgres superuser, REVOKE has no effect (see header comment)"
fi

# ── A09: Security Logging & Monitoring ───────────────────────────────────────
echo "--- A09: Logging ---"

auth_failure_count=$(curl -s --get \
  --data-urlencode 'query={app="stock-analyst-api"} |= "auth_failure"' \
  "$LOKI_URL/loki/api/v1/query_range" 2>/dev/null \
  | jq -r '[.data.result[].values[]] | length' 2>/dev/null || echo "0")
if [[ "${auth_failure_count:-0}" -ge 1 ]]; then
  pass "auth failures are logged to Loki as a queryable event ($auth_failure_count entries)"
else
  warn "auth failures are logged to Loki as a queryable event" \
    "0 entries found — apps/api/middleware/auth.py currently raises 401s without a structured 'auth_failure' log event; add one before relying on this for detection"
fi

# ── SSRF: fetch_url allowlist ─────────────────────────────────────────────────
echo "--- SSRF: fetch_url allowlist ---"

ssrf_result=$(python3 -c "
import asyncio, sys
sys.path.insert(0, '$REPO_ROOT/packages/agents/src')
sys.path.insert(0, '$REPO_ROOT/packages/shared/src')
from agents.industry_analyst.tools import fetch_url

async def main():
    try:
        await fetch_url('http://169.254.169.254/latest/meta-data/')
        print('NOT_BLOCKED')
    except ValueError as e:
        print(f'BLOCKED: {e}')

asyncio.run(main())
" 2>&1 | tail -1)
if [[ "$ssrf_result" == BLOCKED:* ]]; then
  pass "SSRF blocked for non-allowlisted domain ($ssrf_result)"
else
  fail "SSRF blocked for non-allowlisted domain" "expected a ValueError, got: $ssrf_result"
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo "=== AUDIT RESULT: $PASS passed, $FAIL failed, $WARN warnings ==="
if [[ $FAIL -gt 0 ]]; then
  echo "FAILED: ${FAILED_NAMES[*]}"
fi
if [[ $WARN -gt 0 ]]; then
  echo "WARNED: ${WARNED_NAMES[*]}"
fi
if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
exit 0
