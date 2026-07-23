"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { Sparkles } from "lucide-react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { IndustryPrimerView } from "@/components/research/industry-primer-view"
import { useCoverage } from "@/lib/queries/coverages"
import { industryPrimerKey, useIndustryPrimer, useRunIndustryAnalysis } from "@/lib/queries/industry"
import { useTaskStatus } from "@/lib/queries/documents"
import { useQueryClient } from "@tanstack/react-query"

export default function IndustryResearchPage() {
  const params = useParams<{ id: string }>()
  const coverageId = params.id
  const queryClient = useQueryClient()

  const { data: coverage } = useCoverage(coverageId)
  const { data: primer, isLoading: isPrimerLoading } = useIndustryPrimer(coverage?.industry_id)

  const [industryName, setIndustryName] = useState("")
  const [taskId, setTaskId] = useState<string | null>(null)
  const runAnalysis = useRunIndustryAnalysis(coverageId)

  const { data: task } = useTaskStatus(taskId)
  useEffect(() => {
    if (task?.status === "completed" && taskId) {
      // Primer row was just written by the agent — refetch it once, then
      // stop tracking this task so we don't invalidate on every poll tick.
      queryClient.invalidateQueries({ queryKey: industryPrimerKey(coverage?.industry_id) })
      setTaskId(null)
    }
  }, [task?.status, taskId, coverage?.industry_id, queryClient])

  function handleRun() {
    const name = industryName.trim() || coverage?.industry_name || ""
    if (!name) return
    runAnalysis.mutate(name, {
      onSuccess: (result) => setTaskId(result.task_id),
    })
  }

  const isRunning = runAnalysis.isPending || (!!taskId && task?.status !== "failed")

  if (isPrimerLoading && coverage?.industry_id) {
    return (
      <div>
        <h2 className="mb-2 text-xl font-semibold text-slate-900">Industry</h2>
        <p className="text-slate-500">Loading industry primer…</p>
      </div>
    )
  }

  if (primer?.primer_content) {
    return (
      <div className="space-y-4">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold text-slate-900">{primer.name}</h2>
          <span className="text-xs text-slate-400">
            {primer.word_count?.toLocaleString()} words · {primer.llm_used}
          </span>
        </div>
        <IndustryPrimerView content={primer.primer_content} />
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-slate-900">Industry</h2>
      <div className="rounded-lg border bg-white p-8 text-center">
        <p className="mb-4 text-slate-500">
          No industry primer yet for {coverage?.industry_name ?? "this coverage"}. Generate one to
          unlock research for every stock in this industry.
        </p>
        <div className="mx-auto flex max-w-sm gap-2">
          <Input
            placeholder={coverage?.industry_name ?? "Industry name (e.g. Enterprise Software)"}
            value={industryName}
            onChange={(e) => setIndustryName(e.target.value)}
            disabled={isRunning}
          />
          <Button onClick={handleRun} disabled={isRunning}>
            <Sparkles className="mr-2 h-4 w-4" />
            {isRunning ? "Running…" : "Run Industry Analysis"}
          </Button>
        </div>
        {task?.status === "failed" && (
          <p className="mt-3 text-sm text-red-500">Analysis failed: {task.error}</p>
        )}
      </div>
    </div>
  )
}
