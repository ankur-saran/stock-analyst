import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { apiFetch } from "@/lib/api"
import type { Coverage, Industry } from "@/lib/types"

export function useCoverage(coverageId: string) {
  return useQuery({
    queryKey: ["coverages", coverageId] as const,
    queryFn: () => apiFetch<Coverage>(`/coverages/${coverageId}`),
    enabled: !!coverageId,
  })
}

export function useIndustries() {
  return useQuery({
    queryKey: ["industries"] as const,
    queryFn: () => apiFetch<Industry[]>("/industries"),
    staleTime: 5 * 60_000,
  })
}

interface CreateCoverageVariables {
  ticker: string
  companyName: string
  exchange: string
  industryId: string | null
}

export function useCreateCoverage() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: CreateCoverageVariables) =>
      apiFetch<Coverage>("/coverages", {
        method: "POST",
        body: JSON.stringify({
          ticker: variables.ticker,
          company_name: variables.companyName,
          exchange: variables.exchange,
          industry_id: variables.industryId,
        }),
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["coverages"] })
    },
  })
}
