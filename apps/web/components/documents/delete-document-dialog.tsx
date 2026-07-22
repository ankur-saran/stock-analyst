"use client"

import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog"
import { useToast } from "@/hooks/use-toast"
import { useDeleteDocument } from "@/lib/queries/documents"
import type { DocumentRow } from "@/lib/types"

interface DeleteDocumentDialogProps {
  coverageId: string
  document: DocumentRow | null
  onOpenChange: (open: boolean) => void
}

export function DeleteDocumentDialog({ coverageId, document, onOpenChange }: DeleteDocumentDialogProps) {
  const { toast } = useToast()
  const deleteMutation = useDeleteDocument(coverageId)

  const isIndexing = document?.ingest_status === "indexing"

  function handleConfirm(event: React.MouseEvent<HTMLButtonElement>) {
    // AlertDialogAction closes on click by default; we want the dialog to
    // stay open (showing "Deleting…") until the mutation actually settles.
    event.preventDefault()
    if (!document) return
    deleteMutation.mutate(document.id, {
      onSuccess: () => {
        onOpenChange(false)
      },
      onError: (error) => {
        toast({
          title: "Failed to delete document",
          description: error instanceof Error ? error.message : "Please try again.",
          variant: "destructive",
        })
      },
    })
  }

  return (
    <AlertDialog open={!!document} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Delete document?</AlertDialogTitle>
          <AlertDialogDescription>
            Delete {document?.file_name}? This will remove {document?.chunk_count ?? 0} indexed
            chunks and cannot be undone.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={deleteMutation.isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            onClick={handleConfirm}
            disabled={isIndexing || deleteMutation.isPending}
            className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
          >
            {deleteMutation.isPending ? "Deleting…" : "Delete"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}
