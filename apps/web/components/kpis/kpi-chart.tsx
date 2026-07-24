import {
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { KpiYoyBadge } from "@/components/kpis/kpi-yoy-badge"
import type { KpiDataPoint, KpiSeries } from "@/lib/types"

const ACCENT = "#4f46e5" // indigo-600 -- single hue for the metric itself, weight/dash carry meaning
const RESTATED = "#d97706" // amber-600 -- reserved for the restatement callout only

const _ACRONYMS = new Set([
  "arr", "mrr", "nrr", "cac", "ltv", "dau", "mau", "nim", "roe", "roa",
  "fcf", "eps", "npl", "cet1",
])

function formatKpiName(name: string): string {
  return name
    .split("_")
    .map((word) => (_ACRONYMS.has(word.toLowerCase()) ? word.toUpperCase() : word.charAt(0).toUpperCase() + word.slice(1)))
    .join(" ")
}

// "Restated from 1234.0 to 1300.0" -> 1234.0 -- written by
// agents.kpi_tracker.tools.upsert_kpi_timeseries; parsed back out here so the
// chart can plot the old value as its own point next to the new one.
function parseRestatedFrom(note: string | null): number | null {
  if (!note) return null
  const match = note.match(/Restated from (-?[\d.]+) to/)
  return match ? Number(match[1]) : null
}

interface ChartRow {
  period: string
  quarterlyValue: number | null
  annualValue: number | null
  restated: number | null
  citationDoc?: string
  citationQuote?: string
}

function buildChartRows(dataPoints: KpiDataPoint[]): ChartRow[] {
  const rows: ChartRow[] = []

  for (const point of dataPoints) {
    if (point.is_restated) {
      const oldValue = parseRestatedFrom(point.restatement_note)
      if (oldValue !== null) {
        rows.push({
          period: `${point.period} (prior)`,
          quarterlyValue: null,
          annualValue: null,
          restated: oldValue,
        })
      }
    }

    const isQuarterly = point.period_type === "quarterly"
    rows.push({
      period: point.period,
      quarterlyValue: isQuarterly ? point.value : null,
      annualValue: isQuarterly ? null : point.value,
      restated: point.is_restated ? point.value : null,
      citationDoc: point.citation?.document_name,
      citationQuote: point.citation?.exact_quote,
    })
  }

  return rows
}

function KpiTooltip({
  active,
  payload,
  label,
  unit,
}: {
  active?: boolean
  payload?: Array<{ value: number | null; payload: ChartRow }>
  label?: string
  unit: string
}) {
  if (!active || !payload?.length) return null
  const entry = payload.find((p) => p.value !== null && p.value !== undefined)
  if (!entry) return null
  const row = entry.payload

  return (
    <div className="max-w-xs rounded-md border border-slate-200 bg-white p-3 text-xs shadow-md">
      <p className="font-semibold text-slate-900">{label}</p>
      <p className="text-slate-600">
        {entry.value?.toLocaleString()} {unit}
      </p>
      {row.citationQuote && (
        <p className="mt-1 italic text-slate-500">&ldquo;{row.citationQuote}&rdquo;</p>
      )}
      {row.citationDoc && <p className="mt-1 text-[10px] text-slate-400">{row.citationDoc}</p>}
    </div>
  )
}

export function KpiChart({ series }: { series: KpiSeries }) {
  const rows = buildChartRows(series.data_points)
  const latestYoy = series.data_points[series.data_points.length - 1]?.yoy_change_pct ?? null

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">{formatKpiName(series.kpi_name)}</h3>
        <KpiYoyBadge pct={latestYoy} />
      </div>
      <ResponsiveContainer width="100%" height={220}>
        <ComposedChart data={rows} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
          <XAxis
            dataKey="period"
            tick={{ fontSize: 11, fill: "#64748b" }}
            tickLine={false}
            axisLine={{ stroke: "#e2e8f0" }}
          />
          <YAxis tick={{ fontSize: 11, fill: "#64748b" }} tickLine={false} axisLine={false} width={56} />
          <Tooltip content={<KpiTooltip unit={series.unit} />} />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Line
            type="monotone"
            dataKey="quarterlyValue"
            name="Quarterly"
            stroke={ACCENT}
            strokeWidth={1.5}
            dot={{ r: 3 }}
            connectNulls={false}
          />
          <Line
            type="monotone"
            dataKey="annualValue"
            name="Annual"
            stroke={ACCENT}
            strokeWidth={3}
            dot={{ r: 4 }}
            connectNulls={false}
          />
          <Line
            type="linear"
            dataKey="restated"
            name="Restated"
            stroke={RESTATED}
            strokeWidth={1.5}
            strokeDasharray="4 4"
            dot={{ r: 4, stroke: RESTATED, fill: "#fff" }}
            connectNulls={false}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}
