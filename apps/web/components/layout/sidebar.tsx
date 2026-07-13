"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { signOut } from "next-auth/react"
import type { Session } from "next-auth"
import { BarChart3, Shield, LogOut } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface SidebarProps {
  session: Session
}

const navItems = [
  { href: "/coverages", label: "Coverages", icon: BarChart3, roles: null },
  { href: "/admin", label: "Admin", icon: Shield, roles: ["admin"] },
] as const

export function Sidebar({ session }: SidebarProps) {
  const pathname = usePathname()
  const { user } = session

  return (
    <aside className="w-64 flex-shrink-0 bg-slate-900 text-white flex flex-col h-full">
      <div className="px-6 py-5 border-b border-slate-700">
        <span className="text-base font-semibold tracking-tight">
          Stock Analyst AI
        </span>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {navItems.map(({ href, label, icon: Icon, roles }) => {
          if (roles && !roles.includes(user?.role as never)) return null
          const active = pathname.startsWith(href)
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                active
                  ? "bg-slate-700 text-white"
                  : "text-slate-400 hover:bg-slate-800 hover:text-white"
              )}
            >
              <Icon className="h-4 w-4 flex-shrink-0" />
              {label}
            </Link>
          )
        })}
      </nav>

      <div className="px-4 py-4 border-t border-slate-700 space-y-3">
        <div className="min-w-0">
          <p className="text-xs text-slate-400 truncate">{user?.email}</p>
          <Badge variant="secondary" className="mt-1 text-xs capitalize">
            {user?.role?.replace("_", " ")}
          </Badge>
        </div>
        <Button
          variant="ghost"
          size="sm"
          className="w-full justify-start text-slate-400 hover:text-white hover:bg-slate-800"
          onClick={() => signOut({ callbackUrl: "/login" })}
        >
          <LogOut className="h-4 w-4 mr-2" />
          Logout
        </Button>
      </div>
    </aside>
  )
}
