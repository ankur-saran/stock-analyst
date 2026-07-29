"use client"

import { useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useSetAlertThreshold } from "@/lib/queries/admin"
import type { TenantUsage } from "@/lib/types"

const MODEL_LABEL: Record<string, string> = {
  claude: "Claude",
  "gpt-4o": "GPT-4o",
  local: "Local (Ollama)",
}

function currentMonthCost(tenant: TenantUsage): number {
  if (tenant.monthly_costs.length === 0) return 0
  return tenant.monthly_costs[tenant.monthly_costs.length - 1].cost_usd
}

export function TenantUsagePanel({ tenant }: { tenant: TenantUsage }) {
  const setThreshold = useSetAlertThreshold()
  const [thresholdInput, setThresholdInput] = useState(
    tenant.alert_threshold_usd != null ? String(tenant.alert_threshold_usd) : ""
  )
  const [savedThreshold, setSavedThreshold] = useState(tenant.alert_threshold_usd)
  const [status, setStatus] = useState<"idle" | "saved" | "error">("idle")

  const monthCost = currentMonthCost(tenant)
  const overThreshold = savedThreshold != null && monthCost > savedThreshold

  function handleSaveThreshold() {
    const parsed = thresholdInput.trim() === "" ? null : Number(thresholdInput)
    if (parsed !== null && (Number.isNaN(parsed) || parsed < 0)) {
      setStatus("error")
      return
    }
    setThreshold.mutate(
      { tenantId: tenant.tenant_id, alertThresholdUsd: parsed },
      {
        onSuccess: (result) => {
          setSavedThreshold(result.alert_threshold_usd)
          setStatus("saved")
        },
        onError: () => setStatus("error"),
      }
    )
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{tenant.tenant_name}</h3>
          <p className="text-xs text-slate-500">This month: ${monthCost.toFixed(2)}</p>
        </div>
        {overThreshold && (
          <Badge variant="destructive">Over ${savedThreshold?.toFixed(2)} threshold</Badge>
        )}
      </div>

      <div className="flex items-end gap-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
        <div className="flex-1">
          <Label htmlFor="alert-threshold" className="text-xs text-slate-500">
            Monthly spend alert threshold (USD)
          </Label>
          <Input
            id="alert-threshold"
            type="number"
            min={0}
            step="0.01"
            placeholder="No threshold set"
            value={thresholdInput}
            onChange={(e) => {
              setThresholdInput(e.target.value)
              setStatus("idle")
            }}
            className="mt-1 bg-white"
          />
        </div>
        <Button size="sm" onClick={handleSaveThreshold} disabled={setThreshold.isPending}>
          Save
        </Button>
        {status === "saved" && <span className="pb-2 text-xs text-green-700">Saved</span>}
        {status === "error" && <span className="pb-2 text-xs text-red-600">Invalid value</span>}
      </div>

      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          By Model
        </h4>
        {tenant.by_model.length === 0 ? (
          <p className="text-sm text-slate-400">No usage recorded</p>
        ) : (
          <div className="grid grid-cols-3 gap-2">
            {tenant.by_model.map((m) => (
              <div key={m.llm_used} className="rounded-md border border-slate-200 p-2.5">
                <p className="text-xs text-slate-500">{MODEL_LABEL[m.llm_used] ?? m.llm_used}</p>
                <p className="text-sm font-semibold text-slate-900">${m.cost_usd.toFixed(2)}</p>
                <p className="text-[11px] text-slate-400">{m.tokens_used.toLocaleString()} tokens</p>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
          By Coverage
        </h4>
        {tenant.by_coverage.length === 0 ? (
          <p className="text-sm text-slate-400">No usage recorded</p>
        ) : (
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 text-xs text-slate-500">
                <th className="py-1.5 pr-4 font-medium">Coverage</th>
                <th className="py-1.5 pr-4 font-medium">Tokens</th>
                <th className="py-1.5 pr-4 font-medium">Cost</th>
              </tr>
            </thead>
            <tbody>
              {tenant.by_coverage.map((c) => (
                <tr key={c.coverage_id} className="border-b border-slate-100">
                  <td className="py-1.5 pr-4 font-mono text-xs text-slate-700">{c.ticker}</td>
                  <td className="py-1.5 pr-4 tabular-nums text-slate-700">
                    {c.tokens_used.toLocaleString()}
                  </td>
                  <td className="py-1.5 pr-4 tabular-nums text-slate-700">
                    ${c.cost_usd.toFixed(2)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
