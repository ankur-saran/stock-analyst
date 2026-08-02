#!/bin/bash
# infra/vault/configure_vault.sh — one-time Vault configuration for the
# Stock Analyst AI cluster. Idempotent: every step below is safe to re-run
# (kv put overwrites, secrets/auth enable calls are no-ops if already
# enabled, policy/role writes overwrite in place).
#
# Run AFTER:
#   vault operator init -key-shares=5 -key-threshold=3
#   vault operator unseal   # x3, using three of the five unseal keys
#
# Vault must come up with production-grade Shamir secret sharing (5 shares,
# 3 required) — never `-key-shares=1` outside a laptop demo. Store the 5
# unseal keys and the initial root token split across separate custodians
# (1Password vaults, printed+safe, etc.) — anyone holding 3 of 5 keys can
# unseal and anyone holding the root token owns the whole secrets estate.
#
# The Kubernetes-auth roles created in step 6 are bound to the shared
# "vault-auth" ServiceAccount that every Deployment in
# infra/helm/*/templates/**/deployment.yaml already runs as. Binding is by
# (service account name, namespace) pair, so isolation between services in
# the SAME namespace (e.g. api and keycloak, both in stock-analyst) is only
# as strong as "which roleName did the CSI SecretProviderClass ask for" —
# it is not a hard multi-tenancy boundary. If that gap ever matters, give
# each service its own ServiceAccount and bind roles to that instead.
#
# Required env vars: ANTHROPIC_API_KEY, OPENAI_API_KEY, TAVILY_API_KEY,
# POSTGRES_PASSWORD, MINIO_ROOT_USER, MINIO_ROOT_PASSWORD,
# KEYCLOAK_ADMIN_PASSWORD, KEYCLOAK_CLIENT_SECRET, SECRET_KEY,
# NEXTAUTH_SECRET, LANGSMITH_API_KEY. VAULT_ADDR/VAULT_TOKEN must already be
# set (or you've already run `vault login`) and Vault must be unsealed.
set -euo pipefail

: "${ANTHROPIC_API_KEY:?ANTHROPIC_API_KEY is required}"
: "${OPENAI_API_KEY:?OPENAI_API_KEY is required}"
: "${TAVILY_API_KEY:?TAVILY_API_KEY is required}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required}"
: "${MINIO_ROOT_USER:?MINIO_ROOT_USER is required}"
: "${MINIO_ROOT_PASSWORD:?MINIO_ROOT_PASSWORD is required}"
: "${KEYCLOAK_ADMIN_PASSWORD:?KEYCLOAK_ADMIN_PASSWORD is required}"
: "${KEYCLOAK_CLIENT_SECRET:?KEYCLOAK_CLIENT_SECRET is required}"
: "${SECRET_KEY:?SECRET_KEY is required}"
: "${NEXTAUTH_SECRET:?NEXTAUTH_SECRET is required}"
: "${LANGSMITH_API_KEY:?LANGSMITH_API_KEY is required}"

echo "=== Configuring Vault for Stock Analyst AI ==="

# ── 1. KV v2 secrets engine ──────────────────────────────────────────────────
if ! vault secrets list -format=json | grep -q '"secret/"'; then
  vault secrets enable -path=secret kv-v2
else
  echo "  secret/ kv-v2 already enabled, skipping"
fi

# ── 2. Secrets, grouped by rotation blast-radius, not by consumer ───────────
# Each group is its own KV entry so rotating one (e.g. a compromised LLM key)
# never requires touching, or even reading, the others. The Vault CSI
# SecretProviderClasses in infra/helm/stock-analyst-infra/values.yaml
# reference these exact paths (secret/data/stock-analyst/<group>).
echo "--- Writing secret/stock-analyst/llm-keys ---"
vault kv put secret/stock-analyst/llm-keys \
  ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY}" \
  OPENAI_API_KEY="${OPENAI_API_KEY}" \
  TAVILY_API_KEY="${TAVILY_API_KEY}"

echo "--- Writing secret/stock-analyst/database ---"
vault kv put secret/stock-analyst/database \
  POSTGRES_USER="${POSTGRES_USER:-stockanalyst}" \
  POSTGRES_PASSWORD="${POSTGRES_PASSWORD}" \
  POSTGRES_DB="${POSTGRES_DB:-stockanalyst}"

echo "--- Writing secret/stock-analyst/storage ---"
vault kv put secret/stock-analyst/storage \
  MINIO_ROOT_USER="${MINIO_ROOT_USER}" \
  MINIO_ROOT_PASSWORD="${MINIO_ROOT_PASSWORD}"

echo "--- Writing secret/stock-analyst/auth ---"
vault kv put secret/stock-analyst/auth \
  KEYCLOAK_ADMIN="${KEYCLOAK_ADMIN:-admin}" \
  KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD}" \
  KEYCLOAK_CLIENT_SECRET="${KEYCLOAK_CLIENT_SECRET}" \
  SECRET_KEY="${SECRET_KEY}" \
  NEXTAUTH_SECRET="${NEXTAUTH_SECRET}"

echo "--- Writing secret/stock-analyst/langsmith ---"
vault kv put secret/stock-analyst/langsmith \
  LANGSMITH_API_KEY="${LANGSMITH_API_KEY}"

# ── 3. AppRole auth (for out-of-cluster / CI callers, e.g. the security ────
# audit script and future admin tooling — pods use Kubernetes auth instead,
# see step 6) ─────────────────────────────────────────────────────────────
if ! vault auth list -format=json | grep -q '"approle/"'; then
  vault auth enable approle
else
  echo "  approle auth already enabled, skipping"
fi

vault write auth/approle/role/stock-analyst \
  token_policies="stock-analyst-readonly" \
  token_ttl=1h \
  token_max_ttl=4h

# ── 4. Kubernetes auth (for the Vault CSI provider) ─────────────────────────
if ! vault auth list -format=json | grep -q '"kubernetes/"'; then
  vault auth enable kubernetes
else
  echo "  kubernetes auth already enabled, skipping"
fi

vault write auth/kubernetes/config \
  kubernetes_host="https://kubernetes.default.svc"

# ── 5. Least-privilege policies, one per secret group ────────────────────────
vault policy write stock-analyst-llm-keys - <<'EOF'
path "secret/data/stock-analyst/llm-keys" {
  capabilities = ["read"]
}
EOF

vault policy write stock-analyst-database - <<'EOF'
path "secret/data/stock-analyst/database" {
  capabilities = ["read"]
}
EOF

vault policy write stock-analyst-storage - <<'EOF'
path "secret/data/stock-analyst/storage" {
  capabilities = ["read"]
}
EOF

vault policy write stock-analyst-auth - <<'EOF'
path "secret/data/stock-analyst/auth" {
  capabilities = ["read"]
}
EOF

vault policy write stock-analyst-langsmith - <<'EOF'
path "secret/data/stock-analyst/langsmith" {
  capabilities = ["read"]
}
EOF

# The api/web/celery tiers need the union of everything (they run the agents
# that call every provider). Keep this as the one broad policy rather than
# giving every workload the union — postgres/minio/litellm/keycloak below
# each get only what they individually need.
vault policy write stock-analyst-app - <<'EOF'
path "secret/data/stock-analyst/llm-keys" {
  capabilities = ["read"]
}
path "secret/data/stock-analyst/database" {
  capabilities = ["read"]
}
path "secret/data/stock-analyst/storage" {
  capabilities = ["read"]
}
path "secret/data/stock-analyst/auth" {
  capabilities = ["read"]
}
path "secret/data/stock-analyst/langsmith" {
  capabilities = ["read"]
}
EOF

# Read-only umbrella policy for the AppRole (step 3) — human/CI callers,
# never bound to a workload.
vault policy write stock-analyst-readonly - <<'EOF'
path "secret/data/stock-analyst/*" {
  capabilities = ["read", "list"]
}
path "secret/metadata/stock-analyst/*" {
  capabilities = ["list"]
}
EOF

# ── 6. Kubernetes-auth roles — one per SecretProviderClass roleName ─────────
# bound_service_account_namespaces is the real isolation boundary here: a
# pod in stock-analyst-data can never present a JWT that satisfies the
# "litellm" role's namespace bind, regardless of which SecretProviderClass
# it tries to mount.
vault write auth/kubernetes/role/postgres \
  bound_service_account_names="vault-auth" \
  bound_service_account_namespaces="stock-analyst-data" \
  policies="stock-analyst-database" \
  ttl=1h

vault write auth/kubernetes/role/minio \
  bound_service_account_names="vault-auth" \
  bound_service_account_namespaces="stock-analyst-data" \
  policies="stock-analyst-storage" \
  ttl=1h

vault write auth/kubernetes/role/litellm \
  bound_service_account_names="vault-auth" \
  bound_service_account_namespaces="stock-analyst-infra" \
  policies="stock-analyst-llm-keys" \
  ttl=1h

vault write auth/kubernetes/role/keycloak \
  bound_service_account_names="vault-auth" \
  bound_service_account_namespaces="stock-analyst" \
  policies="stock-analyst-database,stock-analyst-auth" \
  ttl=1h

vault write auth/kubernetes/role/app \
  bound_service_account_names="vault-auth" \
  bound_service_account_namespaces="stock-analyst" \
  policies="stock-analyst-app" \
  ttl=1h

echo "=== Vault configured. Verify with: ==="
echo "  vault kv get secret/stock-analyst/llm-keys"
echo "  vault read auth/kubernetes/role/app"
