"use client"

import { useState } from "react"
import { useParams } from "next/navigation"
import { Cloud, Plus, Trash2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { DeleteDocumentDialog } from "@/components/documents/delete-document-dialog"
import { DocumentStatusBadge } from "@/components/documents/status-badge"
import { QualityScoreBar } from "@/components/documents/quality-score-bar"
import { UploadModal } from "@/components/documents/upload-modal"
import { useCoverage } from "@/lib/queries/coverages"
import { useDocuments, useRetryDocument } from "@/lib/queries/documents"
import type { DocumentRow } from "@/lib/types"
import { formatRelativeTime } from "@/lib/utils"

export default function DocumentsPage() {
  const params = useParams<{ id: string }>()
  const coverageId = params.id

  const { data: coverage } = useCoverage(coverageId)
  const { data: documents, isLoading, isError } = useDocuments(coverageId)
  const retryMutation = useRetryDocument(coverageId)

  const [uploadOpen, setUploadOpen] = useState(false)
  const [uploadInitialTab, setUploadInitialTab] = useState<"upload" | "sec">("upload")
  const [documentToDelete, setDocumentToDelete] = useState<DocumentRow | null>(null)

  function openUpload(tab: "upload" | "sec") {
    setUploadInitialTab(tab)
    setUploadOpen(true)
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-slate-900">Documents</h2>
        <div className="flex gap-2">
          <Button variant="outline" onClick={() => openUpload("sec")}>
            <Cloud className="mr-2 h-4 w-4" />
            Fetch from SEC EDGAR
          </Button>
          <Button onClick={() => openUpload("upload")}>
            <Plus className="mr-2 h-4 w-4" />
            Upload Document
          </Button>
        </div>
      </div>

      <div className="rounded-lg border bg-white">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>File Name</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Period</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Chunks</TableHead>
              <TableHead>Quality</TableHead>
              <TableHead>Ingested</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading && (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-slate-400">
                  Loading documents…
                </TableCell>
              </TableRow>
            )}
            {isError && !isLoading && (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-red-500">
                  Failed to load documents.
                </TableCell>
              </TableRow>
            )}
            {!isLoading && !isError && documents?.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="py-10 text-center text-slate-400">
                  No documents yet. Upload a filing or fetch one from SEC EDGAR.
                </TableCell>
              </TableRow>
            )}
            {documents?.map((doc) => (
              <TableRow key={doc.id}>
                <TableCell className="max-w-xs truncate font-medium">{doc.file_name}</TableCell>
                <TableCell>{doc.filing_type}</TableCell>
                <TableCell>{doc.period}</TableCell>
                <TableCell>
                  <DocumentStatusBadge
                    status={doc.ingest_status}
                    onRetry={
                      doc.ingest_status === "failed" ? () => retryMutation.mutate(doc.id) : undefined
                    }
                    retrying={retryMutation.isPending && retryMutation.variables === doc.id}
                  />
                </TableCell>
                <TableCell>{doc.chunk_count}</TableCell>
                <TableCell>
                  <QualityScoreBar score={doc.quality_score} />
                </TableCell>
                <TableCell className="text-sm text-slate-500">
                  {formatRelativeTime(doc.ingested_at)}
                </TableCell>
                <TableCell className="text-right">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete ${doc.file_name}`}
                    onClick={() => setDocumentToDelete(doc)}
                  >
                    <Trash2 className="h-4 w-4 text-slate-400 hover:text-red-500" />
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>

      <UploadModal
        coverageId={coverageId}
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        initialTab={uploadInitialTab}
        defaultTicker={coverage?.ticker}
      />

      <DeleteDocumentDialog
        coverageId={coverageId}
        document={documentToDelete}
        onOpenChange={(open) => {
          if (!open) setDocumentToDelete(null)
        }}
      />
    </div>
  )
}
