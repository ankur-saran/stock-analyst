"use client"

import { Loader2 } from "lucide-react"

import { ResearchOutput } from "@/components/research/research-output"
import { Button } from "@/components/ui/button"
import { useTaskStream } from "@/hooks/use-task-stream"
import { useLatestOutput, useOutput } from "@/lib/queries/research"
import type { OutputType } from "@/lib/types"

interface AgentRunPanelProps {
  coverageId: string
  outputType: OutputType
  title: string
  taskId: string | null
  isDispatching: boolean
  onRun: () => void
}

/**
 * Controlled panel: `taskId`/`onRun` are owned by the caller so the same
 * component works standalone (bull-case/bear-case pages, one mutation each)
 * and side-by-side (research/page.tsx, both mutations lifted to fire
 * together from "Run Both").
 */
export function AgentRunPanel({
  coverageId,
  outputType,
  title,
  taskId,
  isDispatching,
  onRun,
}: AgentRunPanelProps) {
  const stream = useTaskStream(taskId)
  const { data: latestOutput } = useLatestOutput(coverageId, outputType)
  const isTerminal = stream.status === "complete" || stream.status === "partial"
  const { data: finalOutput } = useOutput(coverageId, isTerminal ? stream.outputId : null)

  const hasStarted = taskId !== null
  const showPriorResult = !hasStarted && !!latestOutput

  return (
    <div className="rounded-lg border bg-white p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900">{title}</h3>
        {(showPriorResult || isTerminal) && (
          <Button variant="outline" size="sm" onClick={onRun} disabled={isDispatching}>
            {isDispatching && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            Regenerate
          </Button>
        )}
      </div>

      {!hasStarted && !latestOutput && (
        <Button onClick={onRun} disabled={isDispatching}>
          {isDispatching ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Preparing analysis…
            </>
          ) : (
            `Generate ${title}`
          )}
        </Button>
      )}

      {showPriorResult && latestOutput && (
        <ResearchOutput
          coverageId={coverageId}
          content={latestOutput.content}
          enforcerStatus={latestOutput.enforcer_status}
          citationCoveragePct={latestOutput.citation_coverage_pct}
        />
      )}

      {hasStarted && (stream.status === "connecting" || stream.status === "streaming") && (
        <ResearchOutput coverageId={coverageId} content={stream.streamedContent} />
      )}

      {hasStarted && isTerminal && (
        <ResearchOutput
          coverageId={coverageId}
          content={finalOutput?.content ?? stream.streamedContent}
          enforcerStatus={stream.status === "partial" ? "partial" : finalOutput?.enforcer_status ?? null}
          citationCoveragePct={finalOutput?.citation_coverage_pct ?? stream.citationCoveragePct}
        />
      )}

      {hasStarted && stream.status === "error" && (
        <div className="rounded-md border border-red-300 bg-red-50 px-4 py-3 text-sm text-red-800">
          {stream.errorDetail || "Something went wrong generating this output."}
        </div>
      )}
    </div>
  )
}
