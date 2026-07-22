"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import { ChevronDown } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { cn } from "@/lib/utils"

interface CoverageTabsProps {
  coverageId: string
}

const RESEARCH_ITEMS = [
  { label: "Industry", href: "research/industry" },
  { label: "Bull Case", href: "research/bull-case" },
  { label: "Bear Case", href: "research/bear-case" },
  { label: "Quarterly", href: "research/quarterly" },
] as const

const tabClass = (active: boolean) =>
  cn(
    "px-3 py-2 text-sm font-medium border-b-2 transition-colors",
    active
      ? "border-slate-900 text-slate-900"
      : "border-transparent text-slate-500 hover:text-slate-900"
  )

export function CoverageTabs({ coverageId }: CoverageTabsProps) {
  const pathname = usePathname()
  const base = `/coverages/${coverageId}`

  const isResearchActive = pathname.startsWith(`${base}/research`)

  return (
    <nav className="flex items-center gap-1 border-b border-slate-200">
      <Link href={`${base}/documents`} className={tabClass(pathname.startsWith(`${base}/documents`))}>
        Documents
      </Link>

      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <button className={cn(tabClass(isResearchActive), "flex items-center gap-1")}>
            Research
            <ChevronDown className="h-3.5 w-3.5" />
          </button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          {RESEARCH_ITEMS.map((item) => (
            <DropdownMenuItem key={item.href} asChild>
              <Link href={`${base}/${item.href}`}>{item.label}</Link>
            </DropdownMenuItem>
          ))}
        </DropdownMenuContent>
      </DropdownMenu>

      <Link href={`${base}/kpis`} className={tabClass(pathname.startsWith(`${base}/kpis`))}>
        KPIs
      </Link>
      <Link href={`${base}/notes`} className={tabClass(pathname.startsWith(`${base}/notes`))}>
        Notes
      </Link>
    </nav>
  )
}
