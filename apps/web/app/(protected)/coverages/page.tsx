import Link from "next/link"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card"
import { CoverageStatusBadge } from "@/components/coverages/coverage-status-badge"
import { NewCoverageSheet } from "@/components/coverages/new-coverage-sheet"
import { apiFetchServer } from "@/lib/api-server"
import type { Coverage } from "@/lib/types"
import { formatRelativeTime } from "@/lib/utils"

export default async function CoveragesPage() {
  const coverages = await apiFetchServer<Coverage[]>("/coverages")

  return (
    <div>
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Coverages</h1>
          <p className="text-slate-500">Equity research coverage for your tenant</p>
        </div>
        <NewCoverageSheet />
      </div>

      {coverages.length === 0 ? (
        <div className="rounded-lg border border-dashed py-16 text-center text-slate-400">
          No coverages yet. Create one to get started.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {coverages.map((coverage) => (
            <Card key={coverage.id}>
              <CardHeader className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="rounded bg-slate-900 px-2 py-1 font-mono text-lg font-semibold text-white">
                    {coverage.ticker}
                  </span>
                  <CoverageStatusBadge status={coverage.status} />
                </div>
                <div>
                  <p className="font-medium text-slate-900">{coverage.company_name}</p>
                  <p className="text-sm text-slate-500">{coverage.industry_name ?? "No industry set"}</p>
                </div>
              </CardHeader>
              <CardContent className="flex items-center justify-between">
                <Badge variant="secondary">
                  {coverage.document_count} {coverage.document_count === 1 ? "document" : "documents"}
                </Badge>
                <span className="text-xs text-slate-400">
                  Updated {formatRelativeTime(coverage.last_updated ?? coverage.created_at)}
                </span>
              </CardContent>
              <CardFooter>
                <Button asChild variant="outline" className="w-full">
                  <Link href={`/coverages/${coverage.id}/documents`}>Open</Link>
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
