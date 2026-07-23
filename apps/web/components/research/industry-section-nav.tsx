"use client"

import { cn } from "@/lib/utils"
import type { ParsedPrimerSection } from "@/lib/industry-primer"

export function IndustrySectionNav({ sections }: { sections: ParsedPrimerSection[] }) {
  function scrollTo(anchorId: string) {
    document.getElementById(anchorId)?.scrollIntoView({ behavior: "smooth", block: "start" })
  }

  return (
    <nav className="sticky top-6 w-56 shrink-0 space-y-1 text-sm">
      {sections.map((section) => (
        <button
          key={section.number}
          onClick={() => scrollTo(`section-${section.number}`)}
          className={cn(
            "block w-full rounded px-2 py-1.5 text-left text-slate-600 hover:bg-slate-100 hover:text-slate-900"
          )}
        >
          {section.number}. {section.name}
        </button>
      ))}
      <button
        onClick={() => scrollTo("section-synthesis")}
        className="block w-full rounded px-2 py-1.5 text-left font-medium text-slate-700 hover:bg-slate-100 hover:text-slate-900"
      >
        Investor Synthesis
      </button>
    </nav>
  )
}
