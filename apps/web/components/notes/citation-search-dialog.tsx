"use client"

import { useEffect, useState } from "react"
import { Search } from "lucide-react"

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { ApiError } from "@/lib/api"
import { searchCitations } from "@/lib/queries/notes"
import type { CitationData } from "@/components/notes/citation-extension"
import type { CitationSearchResult } from "@/lib/types"

interface CitationSearchDialogProps {
  coverageId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  onSelect: (citation: CitationData) => void
}

const DEBOUNCE_MS = 300

export function CitationSearchDialog({
  coverageId,
  open,
  onOpenChange,
  onSelect,
}: CitationSearchDialogProps) {
  const [query, setQuery] = useState("")
  const [results, setResults] = useState<CitationSearchResult[]>([])
  const [isSearching, setIsSearching] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) {
      setQuery("")
      setResults([])
      setError(null)
    }
  }, [open])

  useEffect(() => {
    if (!open || !query.trim()) {
      setResults([])
      return
    }
    setIsSearching(true)
    setError(null)
    const timeout = setTimeout(async () => {
      try {
        const hits = await searchCitations(coverageId, query)
        setResults(hits)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Search failed")
      } finally {
        setIsSearching(false)
      }
    }, DEBOUNCE_MS)
    return () => clearTimeout(timeout)
  }, [coverageId, open, query])

  function handleSelect(result: CitationSearchResult) {
    onSelect({ doc: result.document_name, section: result.section, quote: result.quote })
    onOpenChange(false)
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl">
        <DialogHeader>
          <DialogTitle>Insert citation</DialogTitle>
        </DialogHeader>

        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <Input
            autoFocus
            placeholder="Search indexed documents…"
            className="pl-9"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </div>

        <div className="max-h-80 space-y-1 overflow-y-auto">
          {isSearching && <p className="py-4 text-center text-sm text-slate-500">Searching…</p>}

          {!isSearching && error && (
            <p className="py-4 text-center text-sm text-red-600">{error}</p>
          )}

          {!isSearching && !error && query.trim() && results.length === 0 && (
            <p className="py-4 text-center text-sm text-slate-500">No matches found</p>
          )}

          {!isSearching &&
            results.map((result) => (
              <button
                key={result.chunk_id}
                onClick={() => handleSelect(result)}
                className="w-full rounded-md border border-transparent p-3 text-left text-sm hover:border-slate-200 hover:bg-slate-50"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <span className="font-medium text-slate-900">{result.document_name}</span>
                  <span className="shrink-0 text-xs text-slate-500">{result.section}</span>
                </div>
                <p className="line-clamp-2 text-slate-600">&ldquo;{result.quote}&rdquo;</p>
              </button>
            ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
