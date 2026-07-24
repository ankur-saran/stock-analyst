"use client"

import { useParams } from "next/navigation"

import { KpiChart } from "@/components/kpis/kpi-chart"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useKpis } from "@/lib/queries/kpis"
import type { KpiCategory } from "@/lib/types"

const CATEGORY_LABELS: Record<KpiCategory, string> = {
  financial: "Financial",
  operational: "Operational",
}

export default function KpisPage() {
  const params = useParams<{ id: string }>()
  const coverageId = params.id

  const { data, isLoading, isError } = useKpis(coverageId)

  if (isLoading) {
    return (
      <div>
        <h2 className="mb-2 text-xl font-semibold text-slate-900">KPIs</h2>
        <p className="text-slate-500">Loading KPI data…</p>
      </div>
    )
  }

  if (isError || !data) {
    return (
      <div>
        <h2 className="mb-2 text-xl font-semibold text-slate-900">KPIs</h2>
        <p className="text-slate-500">Could not load KPI data for this coverage.</p>
      </div>
    )
  }

  if (data.kpis.length === 0) {
    return (
      <div>
        <h2 className="mb-2 text-xl font-semibold text-slate-900">KPIs</h2>
        <p className="text-slate-500">
          No KPI data yet. Run the KPI Tracker after uploading and indexing filings.
        </p>
      </div>
    )
  }

  const financial = data.kpis.filter((k) => k.category === "financial")
  const operational = data.kpis.filter((k) => k.category === "operational")
  const defaultTab = financial.length > 0 ? "financial" : "operational"

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-slate-900">KPIs</h2>

      <Tabs defaultValue={defaultTab}>
        <TabsList>
          {financial.length > 0 && <TabsTrigger value="financial">{CATEGORY_LABELS.financial}</TabsTrigger>}
          {operational.length > 0 && (
            <TabsTrigger value="operational">{CATEGORY_LABELS.operational}</TabsTrigger>
          )}
        </TabsList>

        {financial.length > 0 && (
          <TabsContent value="financial" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {financial.map((series) => (
              <KpiChart key={series.kpi_name} series={series} />
            ))}
          </TabsContent>
        )}

        {operational.length > 0 && (
          <TabsContent value="operational" className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {operational.map((series) => (
              <KpiChart key={series.kpi_name} series={series} />
            ))}
          </TabsContent>
        )}
      </Tabs>
    </div>
  )
}
