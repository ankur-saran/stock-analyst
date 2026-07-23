import { CitedText } from "@/components/research/cited-text"
import { IndustrySectionNav } from "@/components/research/industry-section-nav"
import { parsePrimerSections, parseSynthesisBullets } from "@/lib/industry-primer"

function paragraphs(content: string): string[] {
  return content.split(/\n\n+/).map((p) => p.trim()).filter(Boolean)
}

export function IndustryPrimerView({ content }: { content: string }) {
  const sections = parsePrimerSections(content)
  const synthesisBullets = parseSynthesisBullets(content)

  return (
    <div className="flex gap-8">
      <IndustrySectionNav sections={sections} />

      <div className="min-w-0 flex-1 space-y-10">
        {sections.map((section) => (
          <section key={section.number} id={`section-${section.number}`} className="scroll-mt-6">
            <h3 className="mb-3 text-lg font-semibold text-slate-900">
              {section.number}. {section.name}
            </h3>
            <div className="space-y-3 text-sm leading-relaxed text-slate-700">
              {paragraphs(section.content).map((p, i) => (
                <p key={i}>
                  <CitedText text={p} />
                </p>
              ))}
            </div>
          </section>
        ))}

        <section id="section-synthesis" className="scroll-mt-6 rounded-lg border bg-slate-50 p-5">
          <h3 className="mb-3 text-lg font-semibold text-slate-900">Investor Synthesis</h3>
          <ul className="list-disc space-y-2 pl-5 text-sm leading-relaxed text-slate-700">
            {synthesisBullets.map((bullet, i) => (
              <li key={i}>
                <CitedText text={bullet} />
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  )
}
