import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"

import { apiFetch } from "@/lib/api"
import type { CitationSearchResult, CoverageNotes } from "@/lib/types"

export function notesKey(coverageId: string) {
  return ["coverages", coverageId, "notes"] as const
}

export function useNotes(coverageId: string) {
  return useQuery({
    queryKey: notesKey(coverageId),
    queryFn: () => apiFetch<CoverageNotes>(`/coverages/${coverageId}/notes`),
    enabled: !!coverageId,
    // The editor owns the source of truth once loaded — no point refetching
    // over a document the analyst may be actively mid-sentence in.
    staleTime: Infinity,
  })
}

export function useSaveNotes(coverageId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (content: string) =>
      apiFetch<CoverageNotes>(`/coverages/${coverageId}/notes`, {
        method: "POST",
        body: JSON.stringify({ content }),
      }),
    onSuccess: (data) => {
      queryClient.setQueryData(notesKey(coverageId), data)
    },
  })
}

export async function searchCitations(
  coverageId: string,
  query: string
): Promise<CitationSearchResult[]> {
  if (!query.trim()) return []
  return apiFetch<CitationSearchResult[]>(
    `/coverages/${coverageId}/search?q=${encodeURIComponent(query)}`
  )
}
