"use client"

import { useState } from "react"

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { UsageBarChart } from "@/components/admin/usage-bar-chart"
import { TenantUsagePanel } from "@/components/admin/tenant-usage-panel"
import type { TenantUsage } from "@/lib/types"

export function UsageDashboard({ tenants }: { tenants: TenantUsage[] }) {
  const [selectedTenantId, setSelectedTenantId] = useState(tenants[0]?.tenant_id ?? "")
  const selectedTenant = tenants.find((t) => t.tenant_id === selectedTenantId)

  if (tenants.length === 0) {
    return (
      <div className="rounded-lg border border-slate-200 bg-white p-6 text-sm text-slate-500">
        No tenants found.
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <UsageBarChart tenants={tenants} />

      <div className="rounded-lg border border-slate-200 bg-white p-4">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-slate-900">Tenant Detail</h3>
          <Select value={selectedTenantId} onValueChange={setSelectedTenantId}>
            <SelectTrigger className="w-56">
              <SelectValue placeholder="Select a tenant" />
            </SelectTrigger>
            <SelectContent>
              {tenants.map((t) => (
                <SelectItem key={t.tenant_id} value={t.tenant_id}>
                  {t.tenant_name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {selectedTenant && <TenantUsagePanel key={selectedTenant.tenant_id} tenant={selectedTenant} />}
      </div>
    </div>
  )
}
