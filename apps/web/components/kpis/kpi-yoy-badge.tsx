import { ArrowDown, ArrowUp, Minus } from "lucide-react"

import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

export function KpiYoyBadge({ pct }: { pct: number | null }) {
  if (pct === null) {
    return (
      <Badge variant="outline" className="border-slate-300 bg-slate-100 text-slate-500">
        <Minus className="mr-1 h-3 w-3" />
        n/a
      </Badge>
    )
  }

  const isPositive = pct >= 0
  return (
    <Badge
      variant="outline"
      className={cn(
        isPositive
          ? "border-green-300 bg-green-100 text-green-800"
          : "border-red-300 bg-red-100 text-red-800"
      )}
    >
      {isPositive ? <ArrowUp className="mr-1 h-3 w-3" /> : <ArrowDown className="mr-1 h-3 w-3" />}
      {Math.abs(pct).toFixed(1)}% YoY
    </Badge>
  )
}
