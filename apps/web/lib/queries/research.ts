import { useMutation, useQuery } from "@tanstack/react-query"

import { apiFetch } from "@/lib/api"
import type { OutputType, ResearchOutput, RunAgentTaskResponse } from "@/lib/types"

export function outputsKey(coverageId: string, outputType: OutputType) {
  return ["coverages", coverageId, "outputs", outputType] as const
}

// POST /coverages/{id}/tasks/{agentName} -- the existing dispatch endpoint
// (apps/api/routers/tasks.py::run_agent_task_endpoint). agentName is the
// underscored agent name ("lynch_pitch"/"munger_invert"), not a URL slug.
export function useRunAgentTask(coverageId: string, agentName: "lynch_pitch" | "munger_invert") {
  return useMutation({
    mutationFn: () =>
      apiFetch<RunAgentTaskResponse>(`/coverages/${coverageId}/tasks/${agentName}`, {
        method: "POST",
        body: JSON.stringify({ skill: "default", payload: {} }),
      }),
  })
}

// Most recent output of a given type, if one exists -- lets a page open
// showing the last completed run instead of always starting blank.
export function useLatestOutput(coverageId: string, outputType: OutputType) {
  return useQuery({
    queryKey: outputsKey(coverageId, outputType),
    queryFn: async () => {
      const outputs = await apiFetch<ResearchOutput[]>(
        `/coverages/${coverageId}/outputs?output_type=${outputType}`
      )
      return outputs[0] ?? null
    },
    enabled: !!coverageId,
  })
}

// Authoritative content for a specific output, fetched once streaming ends --
// the DB row (not the accumulated stream) is the source of truth for final
// content/citations, since a backgrounded tab can miss chunk events.
export function useOutput(coverageId: string, outputId: string | null) {
  return useQuery({
    queryKey: ["coverages", coverageId, "outputs", "byId", outputId] as const,
    queryFn: () => apiFetch<ResearchOutput>(`/coverages/${coverageId}/outputs/${outputId}`),
    enabled: !!coverageId && !!outputId,
  })
}
