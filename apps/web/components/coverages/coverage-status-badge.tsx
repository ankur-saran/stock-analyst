import { Badge } from "@/components/ui/badge"
import type { CoverageStatus } from "@/lib/types"

const STATUS_STYLES: Record<CoverageStatus, string> = {
  setup: "border-yellow-300 bg-yellow-100 text-yellow-800",
  active: "border-green-300 bg-green-100 text-green-800",
  archived: "border-slate-300 bg-slate-100 text-slate-600",
}

const STATUS_LABELS: Record<CoverageStatus, string> = {
  setup: "Setup",
  active: "Active",
  archived: "Archived",
}

export function CoverageStatusBadge({ status }: { status: CoverageStatus }) {
  return (
    <Badge variant="outline" className={STATUS_STYLES[status]}>
      {STATUS_LABELS[status]}
    </Badge>
  )
}
