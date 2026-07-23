// Mirrors the section/synthesis parsing in
// packages/agents/src/agents/industry_analyst/agent.py so the frontend
// renders exactly the structure the backend validated.

export interface ParsedPrimerSection {
  number: number
  name: string
  content: string
}

const SECTION_RE = /^##\s*(\d+)\.\s*(.+)$/gm
const SYNTHESIS_RE = /^##\s*Investor Synthesis\s*$/m
const BULLET_RE = /^-\s*(.+)$/gm

export function parsePrimerSections(content: string): ParsedPrimerSection[] {
  const headers: { start: number; end: number; number: number; name: string }[] = []
  const re = new RegExp(SECTION_RE)
  let match: RegExpExecArray | null
  while ((match = re.exec(content)) !== null) {
    headers.push({ start: match.index, end: re.lastIndex, number: Number(match[1]), name: match[2].trim() })
  }

  const synthesisMatch = content.match(SYNTHESIS_RE)
  const endOfLastSection = synthesisMatch?.index ?? content.length

  return headers.map((header, i) => {
    const bodyEnd = i + 1 < headers.length ? headers[i + 1].start : endOfLastSection
    return {
      number: header.number,
      name: header.name,
      content: content.slice(header.end, bodyEnd).trim(),
    }
  })
}

export function parseSynthesisBullets(content: string): string[] {
  const synthesisMatch = content.match(SYNTHESIS_RE)
  if (!synthesisMatch || synthesisMatch.index === undefined) return []

  const body = content.slice(synthesisMatch.index + synthesisMatch[0].length)
  const bullets: string[] = []
  const re = new RegExp(BULLET_RE)
  let match: RegExpExecArray | null
  while ((match = re.exec(body)) !== null) {
    bullets.push(match[1].trim())
  }
  return bullets
}
