import { TriangleAlert } from "lucide-react"

import { cn } from "@/lib/utils"

interface QualityScoreBarProps {
  score: number | null | undefined
}

export function QualityScoreBar({ score }: QualityScoreBarProps) {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return <span className="text-xs text-slate-400">Pending</span>
  }

  const clamped = Math.min(Math.max(score, 0), 1)
  const pct = Math.round(clamped * 100)
  const tier = clamped >= 0.8 ? "high" : clamped >= 0.5 ? "mid" : "low"
  const barColor = tier === "high" ? "bg-green-500" : tier === "mid" ? "bg-yellow-500" : "bg-red-500"

  return (
    <div className="flex w-32 items-center gap-2">
      <div className="h-2 flex-1 overflow-hidden rounded-full bg-slate-200">
        <div className={cn("h-full rounded-full", barColor)} style={{ width: `${pct}%` }} />
      </div>
      <span className="w-9 shrink-0 text-right text-xs tabular-nums text-slate-600">{pct}%</span>
      {tier === "low" && <TriangleAlert className="h-3.5 w-3.5 shrink-0 text-red-500" />}
    </div>
  )
}
