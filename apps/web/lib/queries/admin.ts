import { useMutation } from "@tanstack/react-query"

import { apiFetch } from "@/lib/api"

// The usage page is server-rendered (apiFetchServer) and the client
// dashboard holds its own `useState` copy rather than a react-query cache
// entry, so this mutation intentionally has no onSuccess cache side effect
// — callers update local state directly from the mutation result instead.
export function useSetAlertThreshold() {
  return useMutation({
    mutationFn: ({ tenantId, alertThresholdUsd }: { tenantId: string; alertThresholdUsd: number | null }) =>
      apiFetch<{ tenant_id: string; alert_threshold_usd: number | null }>(
        `/admin/tenants/${tenantId}/alert-threshold`,
        { method: "PUT", body: JSON.stringify({ alert_threshold_usd: alertThresholdUsd }) }
      ),
  })
}
