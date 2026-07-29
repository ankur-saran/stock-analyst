"use client"

import { useState } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import type { TenantUsage } from "@/lib/types"

// Fixed-order, CVD-validated categorical palette (dataviz skill,
// references/palette.md) — hue order is the safety mechanism, so tenants
// always draw from these slots in this order, never re-cycled by rank.
const CATEGORICAL_PALETTE = [
  "#2a78d6", // blue
  "#008300", // green
  "#e87ba4", // magenta
  "#eda100", // yellow
  "#1baf7a", // aqua
  "#eb6834", // orange
  "#4a3aa7", // violet
  "#e34948", // red
]
const MAX_CHART_TENANTS = CATEGORICAL_PALETTE.length

function buildMonthlyRows(tenants: TenantUsage[]): Record<string, number | string>[] {
  const months = Array.from(
    new Set(tenants.flatMap((t) => t.monthly_costs.map((m) => m.month)))
  ).sort()

  return months.map((month) => {
    const row: Record<string, number | string> = { month }
    for (const tenant of tenants) {
      const entry = tenant.monthly_costs.find((m) => m.month === month)
      row[tenant.tenant_name] = entry?.cost_usd ?? 0
    }
    return row
  })
}

function UsageTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean
  payload?: Array<{ name: string; value: number; color: string }>
  label?: string
}) {
  if (!active || !payload?.length) return null
  const sorted = [...payload].filter((p) => p.value > 0).sort((a, b) => b.value - a.value)
  if (sorted.length === 0) return null

  return (
    <div className="max-w-xs rounded-md border border-slate-200 bg-white p-3 text-xs shadow-md">
      <p className="mb-1 font-semibold text-slate-900">{label}</p>
      {sorted.map((entry) => (
        <div key={entry.name} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-slate-600">
            <span
              className="h-2 w-2 shrink-0 rounded-full"
              style={{ backgroundColor: entry.color }}
            />
            {entry.name}
          </span>
          <span className="font-medium text-slate-900">${entry.value.toFixed(2)}</span>
        </div>
      ))}
    </div>
  )
}

export function UsageBarChart({ tenants }: { tenants: TenantUsage[] }) {
  const [showTable, setShowTable] = useState(false)
  const chartTenants = tenants.slice(0, MAX_CHART_TENANTS)
  const rows = buildMonthlyRows(chartTenants)

  if (rows.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
        No LLM usage recorded yet.
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">Monthly Cost by Tenant</h3>
        <button
          onClick={() => setShowTable((v) => !v)}
          className="text-xs font-medium text-slate-500 underline-offset-2 hover:text-slate-900 hover:underline"
        >
          {showTable ? "Show chart" : "View as table"}
        </button>
      </div>

      {tenants.length > MAX_CHART_TENANTS && (
        <p className="mb-2 text-xs text-slate-400">
          Showing the top {MAX_CHART_TENANTS} tenants by name order; {tenants.length - MAX_CHART_TENANTS}{" "}
          more not charted.
        </p>
      )}

      {showTable ? (
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-1.5 pr-4 font-medium">Month</th>
                {chartTenants.map((t) => (
                  <th key={t.tenant_id} className="py-1.5 pr-4 font-medium">
                    {t.tenant_name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.month as string} className="border-b border-slate-100">
                  <td className="py-1.5 pr-4 text-slate-700">{row.month}</td>
                  {chartTenants.map((t) => (
                    <td key={t.tenant_id} className="py-1.5 pr-4 tabular-nums text-slate-700">
                      ${Number(row[t.tenant_name] ?? 0).toFixed(2)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={280}>
          <BarChart data={rows} margin={{ top: 8, right: 16, left: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis
              dataKey="month"
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickLine={false}
              axisLine={{ stroke: "#e2e8f0" }}
            />
            <YAxis
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickLine={false}
              axisLine={false}
              width={56}
              tickFormatter={(v) => `$${v}`}
            />
            <Tooltip content={<UsageTooltip />} cursor={{ fill: "#f1f5f9" }} />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {chartTenants.map((tenant, i) => (
              <Bar
                key={tenant.tenant_id}
                dataKey={tenant.tenant_name}
                fill={CATEGORICAL_PALETTE[i]}
                radius={[4, 4, 0, 0]}
                maxBarSize={28}
              />
            ))}
          </BarChart>
        </ResponsiveContainer>
      )}
    </div>
  )
}
