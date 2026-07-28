"use client"

import { useState } from "react"
import { ExternalLink, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { apiFetch } from "@/lib/api"
import type { DocumentRow } from "@/lib/types"

interface CitationModalProps {
  coverageId: string
  open: boolean
  onOpenChange: (open: boolean) => void
  doc: string
  section: string
  quote: string
  matchedDocument: DocumentRow | null
}

export function CitationModal({
  coverageId,
  open,
  onOpenChange,
  doc,
  section,
  quote,
  matchedDocument,
}: CitationModalProps) {
  const [loading, setLoading] = useState(false)

  async function viewInDocument() {
    if (!matchedDocument) return
    setLoading(true)
    try {
      const { url } = await apiFetch<{ url: string }>(
        `/coverages/${coverageId}/documents/${matchedDocument.id}/presigned-url`
      )
      window.open(url, "_blank", "noopener,noreferrer")
    } finally {
      setLoading(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{doc}</DialogTitle>
          <DialogDescription>{section}</DialogDescription>
        </DialogHeader>

        <blockquote className="border-l-2 border-slate-300 pl-4 text-sm italic leading-relaxed text-slate-700">
          &ldquo;{quote}&rdquo;
        </blockquote>

        <Button onClick={viewInDocument} disabled={!matchedDocument || loading}>
          {loading ? (
            <Loader2 className="mr-2 h-4 w-4 animate-spin" />
          ) : (
            <ExternalLink className="mr-2 h-4 w-4" />
          )}
          {matchedDocument ? "View in Document" : "Source document not found"}
        </Button>
      </DialogContent>
    </Dialog>
  )
}
