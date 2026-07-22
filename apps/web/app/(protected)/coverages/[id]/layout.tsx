import { notFound } from "next/navigation"

import { CoverageStatusBadge } from "@/components/coverages/coverage-status-badge"
import { CoverageTabs } from "@/components/coverages/coverage-tabs"
import { apiFetchServer } from "@/lib/api-server"
import type { Coverage } from "@/lib/types"
import { formatRelativeTime } from "@/lib/utils"

export default async function CoverageDetailLayout({
  children,
  params,
}: {
  children: React.ReactNode
  params: { id: string }
}) {
  let coverage: Coverage
  try {
    coverage = await apiFetchServer<Coverage>(`/coverages/${params.id}`)
  } catch {
    notFound()
  }

  return (
    <div className="space-y-6">
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-3">
          <span className="rounded bg-slate-900 px-2 py-1 font-mono text-lg font-semibold text-white">
            {coverage.ticker}
          </span>
          <div>
            <h1 className="text-xl font-semibold text-slate-900">{coverage.company_name}</h1>
            <p className="text-sm text-slate-500">
              Updated {formatRelativeTime(coverage.last_updated ?? coverage.created_at)}
            </p>
          </div>
        </div>
        <CoverageStatusBadge status={coverage.status} />
      </div>

      <CoverageTabs coverageId={coverage.id} />

      <div>{children}</div>
    </div>
  )
}
