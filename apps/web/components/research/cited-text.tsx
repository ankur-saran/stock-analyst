import { Fragment } from "react"

import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip"

// Mirrors CITATION_PATTERN in packages/agents/src/agents/shared/citation_enforcer.py:
// [Document Name, Section]: "exact quote" or [Source Name, URL, Date]: "exact quote"
const CITATION_RE = /\[([^\]]+)\]:\s*"([^"]{10,})"/g

export function CitedText({ text }: { text: string }) {
  const nodes: React.ReactNode[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  let key = 0

  const re = new RegExp(CITATION_RE)
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      nodes.push(<Fragment key={key++}>{text.slice(lastIndex, match.index)}</Fragment>)
    }

    const [, label, quote] = match
    nodes.push(
      <Tooltip key={key++}>
        <TooltipTrigger asChild>
          <span className="cursor-help whitespace-nowrap border-b border-dotted border-slate-400 text-slate-700">
            [{label}]
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-sm whitespace-normal">
          <p className="text-sm italic">&ldquo;{quote}&rdquo;</p>
        </TooltipContent>
      </Tooltip>
    )
    lastIndex = re.lastIndex
  }

  if (lastIndex < text.length) {
    nodes.push(<Fragment key={key++}>{text.slice(lastIndex)}</Fragment>)
  }

  return <>{nodes}</>
}
