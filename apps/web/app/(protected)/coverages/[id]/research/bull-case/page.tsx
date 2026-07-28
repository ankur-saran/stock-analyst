"use client"

import { useState } from "react"
import { useParams } from "next/navigation"

import { AgentRunPanel } from "@/components/research/agent-run-panel"
import { useRunAgentTask } from "@/lib/queries/research"

export default function BullCaseResearchPage() {
  const params = useParams<{ id: string }>()
  const coverageId = params.id
  const [taskId, setTaskId] = useState<string | null>(null)
  const runTask = useRunAgentTask(coverageId, "lynch_pitch")

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-slate-900">Bull Case</h2>
      <AgentRunPanel
        coverageId={coverageId}
        outputType="lynch_pitch"
        title="Bull Case"
        taskId={taskId}
        isDispatching={runTask.isPending}
        onRun={() => {
          setTaskId(null)
          runTask.mutate(undefined, { onSuccess: (data) => setTaskId(data.task_id) })
        }}
      />
    </div>
  )
}
