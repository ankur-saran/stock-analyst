import { getServerSession } from "next-auth"
import { authOptions } from "@/lib/auth-options"

export default async function CoveragesPage() {
  const session = await getServerSession(authOptions)

  return (
    <div>
      <h1 className="text-2xl font-semibold text-slate-900 mb-2">Coverages</h1>
      <p className="text-slate-500 mb-6">Coverage list coming soon</p>
      <p className="text-sm text-slate-400">
        Logged in as {session?.user?.email} ({session?.user?.role})
      </p>
    </div>
  )
}
