#!/bin/bash
# infra/k8s/scripts/bootstrap.sh — full k3s cluster bootstrap for Stock Analyst AI.
#
# Ordering fixes vs. a naive "namespaces -> vault -> data -> ml -> app ->
# infra -> obs" pass:
#   - The stock-analyst-infra chart (Task 5) is what defines every Vault CSI
#     SecretProviderClass — postgres/minio (data), api (app) and litellm
#     (infra) all mount one to get their credentials. It has to install
#     BEFORE those charts, not after, or their pods hang forever waiting on
#     a SecretProviderClass that doesn't exist yet.
#   - There's no `db-migrate` CronJob to invoke by hand: alembic runs as a
#     Helm pre-install/pre-upgrade hook Job bundled into the app chart (see
#     infra/helm/stock-analyst-app/templates/api/migration-job.yaml), so
#     `helm upgrade --install app ...` already blocks on migrations
#     succeeding before the api Deployment rolls out.
#   - local-path (k3s's dynamic provisioner) always sets its PVs to
#     reclaimPolicy: Delete; the constraint that data-tier volumes survive a
#     `helm uninstall` is enforced here with a post-install kubectl patch,
#     since a PVC manifest has no field for it (that's a PV-only property).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"

echo "=== Stock Analyst AI — Cluster Bootstrap ==="

# ── 1. Namespaces ────────────────────────────────────────────────────────────
echo "--- [1/10] Applying namespaces + ResourceQuotas ---"
kubectl apply -f infra/k8s/namespaces/

# ── 2. Vault + Secrets Store CSI Driver + Vault CSI provider ────────────────
# Upstream charts, not defined in this repo — Task 5 only owns the
# SecretProviderClass objects that ride on top of this plumbing.
echo "--- [2/10] Installing Vault + Secrets Store CSI Driver ---"
helm repo add hashicorp https://helm.releases.hashicorp.com >/dev/null
helm repo add secrets-store-csi-driver https://kubernetes-sigs.github.io/secrets-store-csi-driver/charts >/dev/null
helm repo update >/dev/null

helm upgrade --install vault hashicorp/vault \
  -n stock-analyst-infra --wait --timeout 5m
helm upgrade --install secrets-store-csi-driver secrets-store-csi-driver/secrets-store-csi-driver \
  -n stock-analyst-infra --set syncSecret.enabled=true --wait --timeout 5m
helm upgrade --install vault-csi-provider hashicorp/vault-csi-provider \
  -n stock-analyst-infra --wait --timeout 5m

# ── 3. Manual Vault configuration ────────────────────────────────────────────
echo "=== MANUAL STEP: Initialize and unseal Vault, then configure it ==="
echo "Run in another shell:"
echo "  vault operator init -key-shares=5 -key-threshold=3"
echo "  vault operator unseal   # x3, using three of the five unseal keys from init"
echo "  ./infra/vault/configure_vault.sh"
echo "configure_vault.sh creates the Kubernetes-auth roles referenced by each"
echo "SecretProviderClass's roleName (postgres, minio, litellm, keycloak, app),"
echo "the policies scoping each role to only the KV paths it needs, and writes"
echo "the KV secrets at the paths in"
echo "infra/helm/stock-analyst-infra/values.yaml's vaultSecrets list. It binds"
echo "those roles to the 'vault-auth' ServiceAccount that step 4 below creates"
echo "in each namespace that needs one (stock-analyst-data/stock-analyst/"
echo "stock-analyst-infra) — so install order matters: infra-svc before data/app."
read -p "Press ENTER when Vault is configured and sealed..."

# ── 4. Infra services (Traefik routes, LiteLLM, Vault CSI SecretProviderClasses) ──
# Installed before data/app/ml on purpose — see the header comment.
echo "--- [4/10] Installing stock-analyst-infra (LiteLLM, Vault CSI, Traefik routes) ---"
helm upgrade --install infra-svc infra/helm/stock-analyst-infra -n stock-analyst-infra --wait --timeout 5m

# ── 5. Data services ─────────────────────────────────────────────────────────
echo "--- [5/10] Installing stock-analyst-data (Postgres, Qdrant, MinIO, Redis) ---"
helm upgrade --install data infra/helm/stock-analyst-data -n stock-analyst-data --wait --timeout 5m

echo "--- [5b/10] Patching data-tier PV reclaim policy to Retain ---"
for pvc in postgres-data qdrant-data minio-data redis-data; do
  pv=$(kubectl get pvc "$pvc" -n stock-analyst-data -o jsonpath='{.spec.volumeName}' 2>/dev/null || true)
  if [ -n "$pv" ]; then
    kubectl patch pv "$pv" -p '{"spec":{"persistentVolumeReclaimPolicy":"Retain"}}'
  else
    echo "  WARN: no bound PV found for PVC $pvc yet — skipping"
  fi
done

# ── 6. ML services ────────────────────────────────────────────────────────────
echo "--- [6/10] Checking NVIDIA device plugin DaemonSet on the GPU node ---"
if ! kubectl get daemonset -n kube-system nvidia-device-plugin-daemonset >/dev/null 2>&1; then
  echo "  ERROR: nvidia-device-plugin-daemonset not found in kube-system."
  echo "  Install it on the GPU node before continuing (advertises nvidia.com/gpu):"
  echo "    kubectl apply -f https://raw.githubusercontent.com/NVIDIA/k8s-device-plugin/main/deployments/static/nvidia-device-plugin.yml"
  exit 1
fi
echo "--- [6/10] Installing stock-analyst-ml (Ollama, embedding pull job, reranker) ---"
helm upgrade --install ml infra/helm/stock-analyst-ml -n stock-analyst-ml --wait --timeout 10m

# ── 7. App services ───────────────────────────────────────────────────────────
# `helm --wait` here blocks on the pre-install alembic migration Job
# succeeding before the api Deployment is even created — see
# templates/api/migration-job.yaml.
echo "--- [7/10] Installing stock-analyst-app (API, web, Celery, Flower, Keycloak) ---"
helm upgrade --install app infra/helm/stock-analyst-app -n stock-analyst --wait --timeout 10m

# ── 8. Observability ──────────────────────────────────────────────────────────
echo "--- [8/10] Installing stock-analyst-obs (Prometheus, Grafana, Loki, Uptime Kuma) ---"
helm upgrade --install obs infra/helm/stock-analyst-obs -n stock-analyst-obs --wait --timeout 5m

# ── 9. MinIO bucket setup ─────────────────────────────────────────────────────
# minio/minio doesn't ship a Python interpreter or scripts/, so this runs
# scripts/setup_minio.py from the operator's machine against a port-forward,
# using the credentials the Vault CSI sync already wrote to Kubernetes.
echo "--- [9/10] Running MinIO bucket setup ---"
kubectl -n stock-analyst-data port-forward svc/minio 9000:9000 >/tmp/minio-pf.log 2>&1 &
PF_PID=$!
trap 'kill $PF_PID 2>/dev/null || true' EXIT
sleep 3

MINIO_ROOT_USER=$(kubectl get secret minio-credentials -n stock-analyst-data -o jsonpath='{.data.MINIO_ROOT_USER}' | base64 -d)
MINIO_ROOT_PASSWORD=$(kubectl get secret minio-credentials -n stock-analyst-data -o jsonpath='{.data.MINIO_ROOT_PASSWORD}' | base64 -d)

MINIO_ENDPOINT="http://localhost:9000" \
MINIO_ROOT_USER="$MINIO_ROOT_USER" \
MINIO_ROOT_PASSWORD="$MINIO_ROOT_PASSWORD" \
  python scripts/setup_minio.py

kill "$PF_PID" 2>/dev/null || true
trap - EXIT

# ── 10. Done ───────────────────────────────────────────────────────────────
echo "--- [10/10] Bootstrap complete ---"
echo "Run a health check once Traefik and DNS are pointed at the cluster:"
echo "  curl https://api.stock-analyst.internal/health/deep"
