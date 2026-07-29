"use client"

import { useParams } from "next/navigation"

import { AnalystNotesEditor } from "@/components/notes/analyst-notes-editor"

export default function NotesPage() {
  const params = useParams<{ id: string }>()

  return (
    <div>
      <h2 className="mb-2 text-xl font-semibold text-slate-900">Notes</h2>
      <AnalystNotesEditor coverageId={params.id} />
    </div>
  )
}
