import { getServerSession } from "next-auth"
import { redirect } from "next/navigation"

import { authOptions } from "@/lib/auth-options"

// The sidebar already hides the "Admin" link from non-admins, but that's a
// visibility nicety, not access control — nothing previously stopped a
// non-admin from loading /admin directly by URL. This layout is the actual
// guard: every route under (protected)/admin/ renders through it.
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await getServerSession(authOptions)

  if (session?.user?.role !== "admin") {
    redirect("/coverages")
  }

  return <>{children}</>
}
