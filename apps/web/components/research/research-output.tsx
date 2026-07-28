import { Fragment } from "react"

import { CitationTooltip } from "@/components/research/citation-tooltip"
import { Badge } from "@/components/ui/badge"
import type { EnforcerStatus } from "@/lib/types"

// Mirrors CITATION_PATTERN in packages/agents/src/agents/shared/citation_enforcer.py:
// [Document Name, Section]: "exact quote" -- doc and section captured
// separately (unlike cited-text.tsx's single-group version) since the
// CitationModal needs them broken out.
const CITATION_RE = /\[([^\],]+),\s*([^\]]+)\]:\s*"([^"]{10,})"/g

const QUESTION_HEADER_RE = /^###\s*(Q\d+:.+)$/

function renderParagraph(coverageId: string, text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  let key = 0

  const re = new RegExp(CITATION_RE)
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(<Fragment key={key++}>{text.slice(lastIndex, match.index)}</Fragment>)
    }

    const [, doc, section, quote] = match
    nodes.push(
      <CitationTooltip
        key={key++}
        coverageId={coverageId}
        citation={{ doc: doc.trim(), section: section.trim(), quote: quote.trim() }}
      />
    )
    lastIndex = re.lastIndex
  }

  if (lastIndex < text.length) {
    nodes.push(<Fragment key={key++}>{text.slice(lastIndex)}</Fragment>)
  }

  return nodes
}

interface ResearchOutputProps {
  coverageId: string
  content: string
  enforcerStatus?: EnforcerStatus | null
  citationCoveragePct?: number | null
}

/**
 * Renders agent output (bull case / bear case) with inline citations.
 * `content` is re-parsed in full on every render rather than incrementally
 * appended to the DOM -- at this content size (<=900 words per the eval
 * constraints) that's trivially cheap, and it sidesteps a real correctness
 * hazard: diffing partial DOM around a citation that completes mid-buffer.
 * Citation-safe chunk buffering already happens server-side (see
 * BaseAgent._flush_chunk), so `content` never arrives with a split citation.
 */
export function ResearchOutput({
  coverageId,
  content,
  enforcerStatus,
  citationCoveragePct,
}: ResearchOutputProps) {
  const paragraphs = content
    .split(/\n\n+/)
    .map((p) => p.trim())
    .filter(Boolean)

  return (
    <div>
      {enforcerStatus === "partial" && (
        <div className="mb-4 rounded-md border border-orange-300 bg-orange-50 px-4 py-2 text-sm text-orange-800">
          Citation validation partially passed. Manual review recommended.
        </div>
      )}

      <div className="space-y-4 text-sm leading-relaxed text-slate-700">
        {paragraphs.map((p, i) => {
          const headerMatch = QUESTION_HEADER_RE.exec(p)
          if (headerMatch) {
            const [firstLine, ...rest] = p.split("\n")
            const body = rest.join(" ").trim()
            return (
              <div key={i}>
                <h4 className="mb-1 font-semibold text-slate-900">
                  {firstLine.replace(/^###\s*/, "")}
                </h4>
                {body && <p>{renderParagraph(coverageId, body)}</p>}
              </div>
            )
          }
          return <p key={i}>{renderParagraph(coverageId, p)}</p>
        })}
      </div>

      {citationCoveragePct != null && (
        <div className="mt-4 flex justify-end">
          <Badge variant={citationCoveragePct >= 0.95 ? "default" : "secondary"}>
            {(citationCoveragePct * 100).toFixed(0)}% cited
          </Badge>
        </div>
      )}
    </div>
  )
}
