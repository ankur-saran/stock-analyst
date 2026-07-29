"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { EditorContent, useEditor } from "@tiptap/react"
import StarterKit from "@tiptap/starter-kit"
import Placeholder from "@tiptap/extension-placeholder"
import {
  AtSign,
  Bold as BoldIcon,
  Heading2,
  Heading3,
  Italic as ItalicIcon,
  List,
  ListOrdered,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"
import { useNotes, useSaveNotes } from "@/lib/queries/notes"
import { CitationExtension, type CitationData } from "@/components/notes/citation-extension"
import { CitationSearchDialog } from "@/components/notes/citation-search-dialog"

interface AnalystNotesEditorProps {
  coverageId: string
}

const AUTOSAVE_DEBOUNCE_MS = 2000

// No @tailwindcss/typography plugin in this project's tailwind.config.ts —
// rather than pull it in for one component, headings/lists inside the
// editor's HTML output are styled directly via arbitrary-variant selectors.
const EDITOR_CONTENT_CLASS = cn(
  "min-h-[300px] max-w-none px-4 py-3 text-sm leading-6 focus:outline-none",
  "[&_h2]:mb-2 [&_h2]:mt-4 [&_h2]:text-lg [&_h2]:font-semibold [&_h2]:text-slate-900",
  "[&_h3]:mb-1 [&_h3]:mt-3 [&_h3]:text-base [&_h3]:font-semibold [&_h3]:text-slate-900",
  "[&_p]:mb-2 [&_ul]:mb-2 [&_ul]:list-disc [&_ul]:pl-5 [&_ol]:mb-2 [&_ol]:list-decimal [&_ol]:pl-5",
  "[&_p.is-editor-empty:first-child::before]:pointer-events-none [&_p.is-editor-empty:first-child::before]:float-left [&_p.is-editor-empty:first-child::before]:h-0 [&_p.is-editor-empty:first-child::before]:text-slate-400 [&_p.is-editor-empty:first-child::before]:content-[attr(data-placeholder)]"
)

export function AnalystNotesEditor({ coverageId }: AnalystNotesEditorProps) {
  const { data: notes, isLoading } = useNotes(coverageId)
  const saveNotes = useSaveNotes(coverageId)
  const [searchOpen, setSearchOpen] = useState(false)
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved">("idle")
  const saveTimeout = useRef<ReturnType<typeof setTimeout> | null>(null)
  const hasLoadedContent = useRef(false)

  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [2, 3] } }),
      Placeholder.configure({ placeholder: "Write analyst notes… type @ to cite a source" }),
      CitationExtension.configure({ onTriggerSearch: () => setSearchOpen(true) }),
    ],
    editorProps: { attributes: { class: EDITOR_CONTENT_CLASS } },
    onUpdate: ({ editor }) => {
      setSaveState("saving")
      if (saveTimeout.current) clearTimeout(saveTimeout.current)
      saveTimeout.current = setTimeout(() => {
        saveNotes.mutate(editor.getHTML(), { onSuccess: () => setSaveState("saved") })
      }, AUTOSAVE_DEBOUNCE_MS)
    },
  })

  // Push the persisted document into the editor exactly once, after both
  // the editor instance and the fetched notes exist. Doing this in a
  // `useEffect` (vs. `useEditor`'s own `content` option) avoids a render
  // race where the query hasn't resolved yet when the editor first mounts.
  useEffect(() => {
    if (!editor || !notes || hasLoadedContent.current) return
    editor.commands.setContent(notes.content || "")
    hasLoadedContent.current = true
  }, [editor, notes])

  useEffect(() => {
    return () => {
      if (saveTimeout.current) clearTimeout(saveTimeout.current)
    }
  }, [])

  const insertCitation = useCallback(
    (citation: CitationData) => {
      editor?.chain().focus().insertCitation(citation).run()
    },
    [editor]
  )

  if (!editor || isLoading) {
    return (
      <div className="rounded-lg border border-slate-200 p-6 text-sm text-slate-500">
        Loading notes…
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="flex items-center justify-between gap-2 border-b border-slate-200 px-2 py-1.5">
        <div className="flex items-center gap-1">
          <ToolbarButton
            active={editor.isActive("bold")}
            onClick={() => editor.chain().focus().toggleBold().run()}
            label="Bold"
          >
            <BoldIcon className="h-4 w-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("italic")}
            onClick={() => editor.chain().focus().toggleItalic().run()}
            label="Italic"
          >
            <ItalicIcon className="h-4 w-4" />
          </ToolbarButton>
          <div className="mx-1 h-5 w-px bg-slate-200" />
          <ToolbarButton
            active={editor.isActive("heading", { level: 2 })}
            onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
            label="Heading 2"
          >
            <Heading2 className="h-4 w-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("heading", { level: 3 })}
            onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
            label="Heading 3"
          >
            <Heading3 className="h-4 w-4" />
          </ToolbarButton>
          <div className="mx-1 h-5 w-px bg-slate-200" />
          <ToolbarButton
            active={editor.isActive("bulletList")}
            onClick={() => editor.chain().focus().toggleBulletList().run()}
            label="Bullet list"
          >
            <List className="h-4 w-4" />
          </ToolbarButton>
          <ToolbarButton
            active={editor.isActive("orderedList")}
            onClick={() => editor.chain().focus().toggleOrderedList().run()}
            label="Numbered list"
          >
            <ListOrdered className="h-4 w-4" />
          </ToolbarButton>
          <div className="mx-1 h-5 w-px bg-slate-200" />
          <ToolbarButton onClick={() => setSearchOpen(true)} label="Insert citation (@)">
            <AtSign className="h-4 w-4" />
          </ToolbarButton>
        </div>

        <span className="pr-2 text-xs text-slate-400">
          {saveState === "saving" && "Saving…"}
          {saveState === "saved" && "Saved"}
        </span>
      </div>

      <EditorContent editor={editor} />

      <CitationSearchDialog
        coverageId={coverageId}
        open={searchOpen}
        onOpenChange={setSearchOpen}
        onSelect={insertCitation}
      />
    </div>
  )
}

interface ToolbarButtonProps {
  onClick: () => void
  active?: boolean
  label: string
  children: React.ReactNode
}

function ToolbarButton({ onClick, active, label, children }: ToolbarButtonProps) {
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      title={label}
      aria-label={label}
      onClick={onClick}
      className={cn("h-8 w-8", active && "bg-slate-200 text-slate-900")}
    >
      {children}
    </Button>
  )
}
