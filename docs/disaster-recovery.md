# Disaster Recovery Runbook

Operator reference for the Stock Analyst AI k3s cluster. Commands are exact
— copy/paste them. Namespaces: `stock-analyst` (api/web/celery/keycloak),
`stock-analyst-data` (postgres/qdrant/minio/redis), `stock-analyst-ml`
(ollama/reranker), `stock-analyst-infra` (vault/litellm/traefik),
`stock-analyst-obs` (prometheus/grafana/loki/uptime-kuma), `velero`.

## Prerequisites this runbook assumes

- Velero is installed with `--use-node-agent` against the `minio-backup`
  `BackupStorageLocation` (see [`infra/k8s/backup/backup-storage-location.yaml`](../infra/k8s/backup/backup-storage-location.yaml)
  for the exact `velero install` command) and the
  [`daily-full-backup`](../infra/k8s/backup/velero-schedule.yaml) Schedule is
  applied. Confirm a backup has actually run before you need one:
  ```
  velero backup get
  velero backup describe <most-recent-backup-name> --details
  ```
- Backups use File System Backup (kopia), not CSI volume snapshots — k3s's
  default `local-path` StorageClass has no snapshot support. This means
  restoring a PVC also requires restoring the Pod/Deployment that owns it
  (Velero injects a restore-helper init container into that pod to
  repopulate the volume); restoring a PVC in isolation will not bring its
  data back.
- Vault is unsealed with Shamir secret sharing (`-key-shares=5
  -key-threshold=3` — see [`infra/vault/configure_vault.sh`](../infra/vault/configure_vault.sh)).
  Three of the five unseal key holders must be reachable to unseal it.

---

## 1. Pod Crash Loop

**Symptoms:** `kubectl get pods -n <ns>` shows `CrashLoopBackOff`;
Uptime Kuma (`stock-analyst-obs`) flags the corresponding health-check
monitor as down. Note: this cluster does not run kube-state-metrics or
scrape cAdvisor (see `infra/helm/stock-analyst-obs/templates/prometheus/configmap.yaml`
— only fastapi/celery/qdrant/postgres/node-exporter targets are scraped),
so Grafana has no pod-restart-count panel today; Uptime Kuma's HTTP checks
and `kubectl get events` are the actual detection signal, not a dashboard.

**Steps:** None — Kubernetes' own restart-with-backoff already handles
this. Investigate root cause without waiting for a fix to deploy:
```
kubectl get pods -n <namespace> -l app.kubernetes.io/name=<service>
kubectl logs -n <namespace> <pod> --previous
kubectl describe pod -n <namespace> <pod>
```

**Verification:** `kubectl get pods` shows `Running`/`Ready` and restart
count stops climbing; the Uptime Kuma monitor returns to "up".

---

## 2. App Worker Node Failure

**Symptoms:** `kubectl get nodes` shows a node `NotReady`; pods scheduled
on it (per `role: app`/`role: data`/`role: ml` node affinity — see each
chart's `values.yaml global.nodeAffinity`) are stuck `Terminating` or
`Unknown` past the default 5-minute pod-eviction-timeout.

**Steps:**
1. Confirm the node is actually down, not a transient network partition:
   ```
   kubectl get node <node-name> -o wide
   kubectl describe node <node-name>
   ```
2. If genuinely dead, delete the Node object so its Pods are rescheduled
   immediately instead of waiting out the eviction timeout (skip this if
   you expect the node back shortly — deleting is what forces rescheduling
   onto remaining nodes):
   ```
   kubectl delete node <node-name>
   ```
3. Watch pods reschedule onto surviving nodes with matching labels:
   ```
   kubectl get pods -A -o wide --field-selector spec.nodeName=<node-name>
   kubectl get pods -A -o wide -w
   ```
   Note: HPA-managed Deployments (api, celery-worker) will schedule fine if
   capacity exists on remaining nodes; the single-replica `Recreate`-strategy
   ones (postgres, celery-beat, keycloak) will only come back once a node
   with the right `role` label has capacity — if the failed node was the
   sole data node, see Scenario 3/4 instead.
4. Provision the replacement node: join it to k3s with the original node's
   `role` label (`kubectl label node <new-node> role=<app|data|ml>`), per
   the 4-node layout bootstrap.sh assumes.

**Verification:** `kubectl get nodes` shows all 4 nodes `Ready`;
`kubectl get pods -A -o wide` shows every pod `Running` with no node stuck
at reduced capacity.

---

## 3. PostgreSQL Data Corruption

**Symptoms:** `psql` errors like `invalid page in block`, `could not read
block`; the postgres pod itself may be crash-looping if PGDATA won't start
cleanly; `postgres-exporter`'s metrics stop updating.

**Steps:**
1. Stop writes immediately:
   ```
   kubectl scale deployment postgres -n stock-analyst-data --replicas=0
   ```
2. Confirm the backup you're about to restore actually contains postgres
   and pick its name:
   ```
   velero backup get
   BACKUP_NAME=<name from the list above, most recent daily-full-backup-* before corruption>
   ```
3. The existing PV survives PVC deletion (`reclaimPolicy: Retain`, patched
   by `infra/k8s/scripts/bootstrap.sh` step 5b) but will sit `Released` and
   unusable until removed — delete both so Velero can provision a fresh one:
   ```
   PV_NAME=$(kubectl get pvc postgres-data -n stock-analyst-data -o jsonpath='{.spec.volumeName}')
   kubectl delete pvc postgres-data -n stock-analyst-data
   kubectl delete pv "$PV_NAME"
   ```
4. Restore the postgres Deployment + its PVC together — restoring the PVC
   alone will not trigger the FSB restore-helper that actually repopulates
   data:
   ```
   velero restore create postgres-restore-$(date +%s) \
     --from-backup "$BACKUP_NAME" \
     --include-namespaces stock-analyst-data \
     --include-resources deployments,persistentvolumeclaims,persistentvolumes,secrets,configmaps \
     --selector app.kubernetes.io/name=postgres
   ```
5. Watch it finish (`Completed`, not `PartiallyFailed`):
   ```
   velero restore describe postgres-restore-<timestamp> --details
   ```
6. If the Deployment didn't come back at 1 replica on its own:
   ```
   kubectl scale deployment postgres -n stock-analyst-data --replicas=1
   kubectl rollout status deployment/postgres -n stock-analyst-data
   ```
7. **Fallback if the raw volume restore is still inconsistent** (e.g. WAL
   corruption survived the file-level copy): the daily backup's pre-hook
   (`velero-schedule.yaml`) ran `pg_dump` onto the same PVC at
   `pg_dump/backup.sql` before the FSB volume walk, so it was captured too.
   Pull it out and do a logical restore instead:
   ```
   kubectl cp stock-analyst-data/<postgres-pod>:/var/lib/postgresql/data/pg_dump/backup.sql ./backup.sql
   kubectl exec -n stock-analyst-data deploy/postgres -c postgres -- psql -U stockanalyst -d stockanalyst -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
   kubectl exec -i -n stock-analyst-data deploy/postgres -c postgres -- psql -U stockanalyst -d stockanalyst < ./backup.sql
   ```

**Verification:**
```
kubectl exec -n stock-analyst-data deploy/postgres -c postgres -- \
  psql -U stockanalyst -d stockanalyst -c "SELECT count(*) FROM coverages;"
```
Row count is non-zero and plausible for your last known-good state; API
health check confirms end-to-end:
```
curl -s https://api.stock-analyst.internal/health/deep
```

---

## 4. Full Cluster Loss

**Symptoms:** All 4 nodes unreachable / cluster destroyed (hardware loss,
accidental `k3s-uninstall.sh`, etc.).

**Estimated RTO: 4 hours.** Budget: ~30m node provisioning + k3s install,
~30m Vault re-init and secret re-injection, ~1h data-tier restore (the
1Ti postgres-data + 500Gi qdrant-data + 10Ti minio-data volumes are what
dominates this — actual time scales with how much of those volumes is
really in use, not their provisioned size), ~1h app/ml tier install and
warm-up (Ollama repulling its embedding model, reranker cold start),
remainder as buffer for the inevitable manual step that doesn't go cleanly.

**Steps:**
1. Provision a fresh 4-node k3s cluster matching the original `role` node
   labels (`app`, `data`, `ml`, plus whichever node hosts `infra`/`obs` in
   your topology).
2. Install Velero pointed at the **same offsite MinIO backup bucket** —
   this is why the bucket lives outside the cluster (see the header comment
   in `infra/k8s/backup/backup-storage-location.yaml`): it has to survive
   the very event that just took out the cluster.
   ```
   velero install --provider aws --plugins velero/velero-plugin-for-aws:v1.9.0 \
     --bucket velero-backups --secret-file ./credentials-velero --use-node-agent \
     --backup-location-config region=us-east-1,s3ForcePathStyle=true,s3Url=http://<offsite-minio-host>:9000 \
     --namespace velero
   kubectl apply -f infra/k8s/namespaces/
   kubectl apply -f infra/k8s/backup/backup-storage-location.yaml
   kubectl apply -f infra/k8s/backup/velero-schedule.yaml
   ```
3. Restore everything from the latest backup:
   ```
   velero backup get
   velero restore create full-restore-$(date +%s) --from-backup <latest-backup-name>
   velero restore describe full-restore-<timestamp> --details
   ```
4. Vault's data directory was part of `stock-analyst-infra` and comes back
   via the restore above, but a **sealed, restored Vault is not the same as
   a working one** — Vault still needs unsealing with the *original* 5
   unseal keys (they're held by custodians outside the cluster per
   `infra/vault/configure_vault.sh`'s header comment, precisely so this
   step is possible):
   ```
   vault operator unseal   # x3, using 3 of the 5 original unseal keys
   vault kv get secret/stock-analyst/llm-keys   # confirms the restored KV data is intact
   ```
   If the unseal keys themselves are unrecoverable (e.g. a custodian's
   1Password vault was also destroyed), Vault's raft/storage backend is
   unrecoverable too — treat it as case (b) below instead of (a):
   - (a) Unseal keys recoverable → done, skip to step 5.
   - (b) Unseal keys lost → re-init from scratch and re-inject every
     secret (this is why every credential this cluster uses ultimately
     traces back to Vault and not to a `.env` file — there's exactly one
     script to re-run):
     ```
     vault operator init -key-shares=5 -key-threshold=3
     vault operator unseal   # x3
     ANTHROPIC_API_KEY=... OPENAI_API_KEY=... TAVILY_API_KEY=... \
     POSTGRES_PASSWORD=... MINIO_ROOT_USER=... MINIO_ROOT_PASSWORD=... \
     KEYCLOAK_ADMIN_PASSWORD=... KEYCLOAK_CLIENT_SECRET=... SECRET_KEY=... \
     NEXTAUTH_SECRET=... LANGSMITH_API_KEY=... \
       ./infra/vault/configure_vault.sh
     ```
     Every one of those values must come from your own secret custodian
     (password manager, HSM, etc.) — never from this repo or from Postgres,
     since Postgres itself is one of the things you're restoring.
5. Re-deploy application charts (they'll pick up the restored/re-seeded
   Vault secrets via the CSI SecretProviderClasses on first mount):
   ```
   ./infra/k8s/scripts/bootstrap.sh
   ```

**Verification:**
```
kubectl get pods -A | grep -v Running
curl -s https://api.stock-analyst.internal/health/deep
velero backup get   # confirms the daily schedule is running again on the new cluster
```
`kubectl get pods -A` returns nothing but `Running`/`Completed` rows, deep
health check reports all dependencies OK.

---

## 5. Qdrant Vector Store Corruption

**Symptoms:** Qdrant pod crash-looping on startup, or `qdrant_client`
health calls returning errors; RAG search results silently empty or wrong
despite `documents.ingest_status = 'completed'` in Postgres. Postgres and
MinIO are unaffected — the source documents are intact in MinIO
(`Document.storage_path`), and their embeddings just need to be recomputed.

**Steps:**
1. Confirm postgres/minio are healthy first (if they're not, this is
   actually Scenario 3 or a MinIO variant, not this one).
2. Recreate Qdrant's volume:
   ```
   kubectl scale deployment qdrant -n stock-analyst-data --replicas=0
   PV_NAME=$(kubectl get pvc qdrant-data -n stock-analyst-data -o jsonpath='{.spec.volumeName}')
   kubectl delete pvc qdrant-data -n stock-analyst-data
   kubectl delete pv "$PV_NAME"
   kubectl scale deployment qdrant -n stock-analyst-data --replicas=1
   kubectl rollout status deployment/qdrant -n stock-analyst-data
   ```
   (`stock-analyst-data`'s Helm chart recreates `qdrant-data` from
   `values.yaml`'s `qdrant.storage` size on the next reconcile — a plain
   `helm upgrade data infra/helm/stock-analyst-data -n stock-analyst-data`
   also works if you'd rather not hand-delete the PVC/PV.)
3. Re-run ingestion for every document so Qdrant gets fresh points. From
   the project root, with `REDIS_URL`/`POSTGRES_*` reachable (port-forward
   both if running from outside the cluster, same as
   `infra/k8s/scripts/bootstrap.sh` does for MinIO):
   ```
   python scripts/reindex_all.py --dry-run          # sanity-check the document count first
   python scripts/reindex_all.py                    # full cluster: every tenant, every coverage
   python scripts/reindex_all.py --coverage-id <id>  # narrower: just one coverage
   ```
4. Track completion via Flower (`stock-analyst` namespace) or:
   ```
   kubectl exec -n stock-analyst-data deploy/postgres -c postgres -- \
     psql -U stockanalyst -d stockanalyst -c \
     "SELECT ingest_status, count(*) FROM documents GROUP BY ingest_status;"
   ```

**Verification:** every document reaches `ingest_status = 'completed'`
(watch for `review_needed`, which means the pipeline flagged something —
that's a per-document data-quality issue, not a sign the reindex failed);
a search against a known coverage returns results again:
```
curl -s -H "Authorization: Bearer $TEST_JWT" \
  "https://api.stock-analyst.internal/coverages/<coverage-id>/search?q=revenue"
```

---

## 6. LLM API Key Compromise

**Symptoms:** Anthropic/OpenAI usage dashboard shows unexpected spend or
requests from unrecognized IPs; a key leaked in a log, screenshot, or
public commit.

**Steps:**
1. Rotate the key in Vault. Use `vault kv patch`, **not** `vault kv put` —
   `llm-keys` holds three keys (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `TAVILY_API_KEY`); `kv put` replaces the entire secret version and would
   silently wipe the other two:
   ```
   vault kv patch secret/stock-analyst/llm-keys ANTHROPIC_API_KEY="<new_key>"
   ```
2. Force every pod holding the old key in its mounted/synced Secret to
   re-read from Vault. The Vault CSI driver only re-syncs on a poll
   interval or pod restart — don't wait for the poll:
   ```
   kubectl rollout restart deployment/api -n stock-analyst
   kubectl rollout restart deployment/celery-worker -n stock-analyst
   kubectl rollout restart deployment/litellm -n stock-analyst-infra
   ```
3. Invalidate the compromised key at the provider console (Anthropic/OpenAI)
   so it stops working even if it's cached somewhere this runbook didn't
   reach (a laptop `.env`, a CI secret, etc.).
4. If the compromise vector is unknown, also rotate `OPENAI_API_KEY` and
   `TAVILY_API_KEY` in the same `kv patch` call rather than one key at a
   time, and check `agent_audit_log` for anomalous activity in the window
   the key was exposed:
   ```
   kubectl exec -n stock-analyst-data deploy/postgres -c postgres -- \
     psql -U stockanalyst -d stockanalyst -c \
     "SELECT agent_name, action, created_at FROM agent_audit_log WHERE created_at > now() - interval '7 days' ORDER BY created_at DESC LIMIT 100;"
   ```

**Verification:**
```
vault kv get secret/stock-analyst/llm-keys   # new value present, OPENAI_API_KEY/TAVILY_API_KEY unchanged
kubectl get pods -n stock-analyst -l app.kubernetes.io/name=api    # all Running post-restart
curl -s https://api.stock-analyst.internal/health/deep             # llm provider check passes
```
Provider console confirms the old key shows `revoked`/`inactive` and zero
new requests against it.
