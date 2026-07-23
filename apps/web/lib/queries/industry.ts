import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { apiFetch } from "@/lib/api"
import type { IndustryAnalysisTaskResponse, IndustryPrimer } from "@/lib/types"

export function industryPrimerKey(industryId: string | null | undefined) {
  return ["industries", industryId] as const
}

export function useIndustryPrimer(industryId: string | null | undefined) {
  return useQuery({
    queryKey: industryPrimerKey(industryId),
    queryFn: () => apiFetch<IndustryPrimer>(`/industries/${industryId}`),
    enabled: !!industryId,
  })
}

export function useRunIndustryAnalysis(coverageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (industryName: string) =>
      apiFetch<IndustryAnalysisTaskResponse>(`/coverages/${coverageId}/tasks/industry-analysis`, {
        method: "POST",
        body: JSON.stringify({ industry_name: industryName }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["coverages", coverageId] })
    },
  })
}
