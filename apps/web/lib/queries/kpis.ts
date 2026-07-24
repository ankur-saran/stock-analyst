import { useQuery } from "@tanstack/react-query"

import { apiFetch } from "@/lib/api"
import type { KpiListResponse } from "@/lib/types"

export function kpisKey(coverageId: string) {
  return ["coverages", coverageId, "kpis"] as const
}

export function useKpis(coverageId: string) {
  return useQuery({
    queryKey: kpisKey(coverageId),
    queryFn: () => apiFetch<KpiListResponse>(`/coverages/${coverageId}/kpis`),
    enabled: !!coverageId,
  })
}
