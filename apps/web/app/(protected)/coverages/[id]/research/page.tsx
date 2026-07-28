"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"

import { AgentRunPanel } from "@/components/research/agent-run-panel"
import { Button } from "@/components/ui/button"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useRunAgentTask } from "@/lib/queries/research"

// Deliberately a runtime breakpoint check, not `hidden md:grid` / `md:hidden`
// CSS toggling: both AgentRunPanel instances hold live WebSocket connections
// (via useTaskStream), so having both the desktop-grid and mobile-tabs trees
// mounted at once -- just one hidden by CSS -- would open two sockets per
// panel. This renders exactly one structural tree at a time.
function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(false)

  useEffect(() => {
    const mql = window.matchMedia("(min-width: 768px)")
    setIsDesktop(mql.matches)
    const onChange = (e: MediaQueryListEvent) => setIsDesktop(e.matches)
    mql.addEventListener("change", onChange)
    return () => mql.removeEventListener("change", onChange)
  }, [])

  return isDesktop
}

export default function ResearchOverviewPage() {
  const params = useParams<{ id: string }>()
  const coverageId = params.id
  const isDesktop = useIsDesktop()

  const [bullTaskId, setBullTaskId] = useState<string | null>(null)
  const [bearTaskId, setBearTaskId] = useState<string | null>(null)
  const runBull = useRunAgentTask(coverageId, "lynch_pitch")
  const runBear = useRunAgentTask(coverageId, "munger_invert")

  function runBullCase() {
    setBullTaskId(null)
    runBull.mutate(undefined, { onSuccess: (data) => setBullTaskId(data.task_id) })
  }

  function runBearCase() {
    setBearTaskId(null)
    runBear.mutate(undefined, { onSuccess: (data) => setBearTaskId(data.task_id) })
  }

  const bullPanel = (
    <AgentRunPanel
      coverageId={coverageId}
      outputType="lynch_pitch"
      title="Bull Case"
      taskId={bullTaskId}
      isDispatching={runBull.isPending}
      onRun={runBullCase}
    />
  )
  const bearPanel = (
    <AgentRunPanel
      coverageId={coverageId}
      outputType="munger_invert"
      title="Bear Case"
      taskId={bearTaskId}
      isDispatching={runBear.isPending}
      onRun={runBearCase}
    />
  )

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-slate-900">Bull vs Bear</h2>
        <Button
          onClick={() => {
            runBullCase()
            runBearCase()
          }}
          disabled={runBull.isPending || runBear.isPending}
        >
          Run Both
        </Button>
      </div>

      {isDesktop ? (
        <div className="grid grid-cols-2 gap-6">
          {bullPanel}
          {bearPanel}
        </div>
      ) : (
        <Tabs defaultValue="bull">
          <TabsList>
            <TabsTrigger value="bull">Bull Case</TabsTrigger>
            <TabsTrigger value="bear">Bear Case</TabsTrigger>
          </TabsList>
          <TabsContent value="bull">{bullPanel}</TabsContent>
          <TabsContent value="bear">{bearPanel}</TabsContent>
        </Tabs>
      )}
    </div>
  )
}
