import { Extension } from "@tiptap/core"

export interface CitationData {
  doc: string
  section: string
  quote: string
}

export interface CitationOptions {
  onTriggerSearch: () => void
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    citation: {
      insertCitation: (citation: CitationData) => ReturnType
    }
  }
}

// `@` is bound directly rather than a modifier combo, so typing it never
// inserts a literal "@" — it always opens the citation search dialog
// instead. The dialog is notified via `options.onTriggerSearch`, a plain
// callback wired up through `.configure()`, rather than `editor.emit(...)`
// with a made-up event name — Tiptap's Editor extends a typed EventEmitter
// whose event map doesn't include arbitrary custom names without also
// augmenting that type, and a configured callback is the more idiomatic
// way for a Tiptap extension to talk back to the component that mounted it.
export const CitationExtension = Extension.create<CitationOptions>({
  name: "citation",

  addOptions() {
    return {
      onTriggerSearch: () => {},
    }
  },

  addCommands() {
    return {
      insertCitation:
        (citation: CitationData) =>
        ({ commands }) => {
          const text = `[${citation.doc}, ${citation.section}]: "${citation.quote}" `
          return commands.insertContent(text)
        },
    }
  },

  addKeyboardShortcuts() {
    return {
      "@": () => {
        this.options.onTriggerSearch()
        return true
      },
    }
  },
})
