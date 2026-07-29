import { apiFetchServer } from "@/lib/api-server"
import { UsageDashboard } from "@/components/admin/usage-dashboard"
import type { UsageResponse } from "@/lib/types"

export default async function AdminUsagePage() {
  const usage = await apiFetchServer<UsageResponse>("/admin/usage")

  return (
    <div className="space-y-6">
      <h1 className="text-xl font-semibold text-slate-900">LLM Usage &amp; Cost</h1>
      <UsageDashboard tenants={usage.tenants} />
    </div>
  )
}
