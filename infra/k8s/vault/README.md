# Vault CSI SecretProviderClasses

There are no standalone manifests in this directory. `SecretProviderClass`
objects for every service (api/web/celery under `app-secrets`, `litellm`,
`keycloak`, `postgres`, `minio`) are rendered by the existing generic
template at
[`infra/helm/stock-analyst-infra/templates/vault-csi/csp.yaml`](../../helm/stock-analyst-infra/templates/vault-csi/csp.yaml),
driven by the `vaultSecrets` list in
[`infra/helm/stock-analyst-infra/values.yaml`](../../helm/stock-analyst-infra/values.yaml).

Hand-written manifests here would collide with those Helm-managed objects —
same `name`+`namespace`, different owner — and `helm upgrade` refuses to
reconcile a resource it doesn't already own ("invalid ownership metadata").
Adding a new service's secrets means adding an entry to `vaultSecrets`, not
a new file in this directory.

See [`infra/vault/configure_vault.sh`](../../vault/configure_vault.sh) for
the Vault-side KV paths, policies and Kubernetes-auth roles each
`SecretProviderClass.spec.parameters.roleName` depends on.
