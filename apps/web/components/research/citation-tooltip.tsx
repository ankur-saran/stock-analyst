"use client"

import { useState } from "react"

import { CitationModal } from "@/components/research/citation-modal"
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"
import { useDocuments } from "@/lib/queries/documents"
import type { Citation, DocumentRow } from "@/lib/types"

interface CitationTooltipProps {
  coverageId: string
  citation: Citation
}

// Citations only carry a human-readable doc label (e.g. "10-K FY2023"), not a
// document_id -- nothing in the data model links them. Best-effort match
// against the coverage's document list; the modal disables "View in
// Document" when nothing matches confidently.
function findMatchingDocument(citationDoc: string, documents: DocumentRow[] | undefined): DocumentRow | null {
  if (!documents) return null
  const needle = citationDoc.toLowerCase()
  return (
    documents.find((d) => {
      const stem = d.file_name.toLowerCase().replace(/\.[a-z0-9]+$/, "")
      return (
        needle.includes(stem) ||
        stem.includes(needle) ||
        (needle.includes(d.filing_type.toLowerCase()) && needle.includes(d.period.toLowerCase()))
      )
    }) ?? null
  )
}

// Visual style (bracketed label, dotted underline) mirrors the existing
// cited-text.tsx used by the industry primer, for consistency across research
// pages. Hover shows a lightweight preview; clicking opens the full
// CitationModal with the quote and a "View in Document" link.
export function CitationTooltip({ coverageId, citation }: CitationTooltipProps) {
  const [modalOpen, setModalOpen] = useState(false)
  const { data: documents } = useDocuments(coverageId)
  const matchedDocument = findMatchingDocument(citation.doc, documents)

  return (
    <>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={() => setModalOpen(true)}
            className="cursor-pointer whitespace-nowrap border-b border-dotted border-slate-400 text-slate-700 hover:text-slate-900"
          >
            [{citation.doc}, {citation.section}]
          </button>
        </TooltipTrigger>
        <TooltipContent className="max-w-sm whitespace-normal">
          <p className="text-sm font-medium">{citation.doc}</p>
          <p className="text-xs text-muted-foreground">{citation.section}</p>
        </TooltipContent>
      </Tooltip>

      <CitationModal
        coverageId={coverageId}
        open={modalOpen}
        onOpenChange={setModalOpen}
        doc={citation.doc}
        section={citation.section}
        quote={citation.quote}
        matchedDocument={matchedDocument}
      />
    </>
  )
}
