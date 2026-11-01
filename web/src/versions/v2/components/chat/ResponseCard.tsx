import { AlertTriangle, CheckCircle2, Lightbulb, BarChart3 } from 'lucide-react'
import { Markdown } from './Markdown'
import './ResponseCard.css'

// Modules 1/3/4 all use this contract.
const SECTIONS: Array<[string, React.ReactNode, string, string]> = [
  ['Insight', <Lightbulb size={14} />, 'var(--green)', 'var(--green-soft)'],
  ['Analysis', <BarChart3 size={14} />, 'var(--blue)', 'var(--blue-soft)'],
  ['Recommendation', <CheckCircle2 size={14} />, 'var(--emerald)', 'var(--emerald-soft)'],
  ['Risk', <AlertTriangle size={14} />, 'var(--red)', 'var(--red-soft)'],
]

function parseSections(text: string, labels: string[]): Record<string, string> {
  // models often write the section names as markdown headings (**Insight**): treat them like 'Insight:'
  let normalized = text.replace(new RegExp(String.raw`\*\*(${labels.join('|')})\*\*:?`, 'g'), '$1:')
  for (const label of labels) {
    normalized = normalized.replace(new RegExp(`(?<!\\n)${label}:`, 'g'), `\n${label}:`)
  }
  const pattern = new RegExp(`(${labels.join('|')}):\\s*`)
  const parts = normalized.split(pattern)

  const result: Record<string, string> = {}
  let currentKey: string | null = null
  for (const rawPart of parts) {
    const part = rawPart.trim()
    if (!part) continue
    if (labels.includes(part)) {
      currentKey = part
    } else if (currentKey) {
      result[currentKey] = part
      currentKey = null
    }
  }
  return result
}

export function ResponseCard({ text }: { text: string }) {
  // Cognitive/Functional/Causal are internal teaching labels; if a model writes them anyway they are dropped, never shown as headings
  const value = String(text ?? '').replace(/(^|\n)[ \t]*\*{0,2}(Cognitive|Functional|Causal)\*{0,2}[ \t]*:\*{0,2}[ \t]*/g, '$1').replace(/\*\*(Cognitive|Functional|Causal)\*\*:?\s*/g, '')

  if (value.startsWith('Error:')) {
    return (
      <div className="response-error">
        <p>ARIA couldn't put an answer together just now. Please try again in a moment.</p>
      </div>
    )
  }

  let sections = parseSections(
    value,
    SECTIONS.map((s) => s[0]),
  )
  const defs = SECTIONS
  if (Object.keys(sections).length === 0) {
    return (
      <div className="response-plain">
        <Markdown text={value} />
      </div>
    )
  }

  return (
    <div className="response-cards">
      {defs.map(([label, icon, color, bg]) => {
        const content = sections[label]
        if (!content) return null
        return (
          <div key={label} className="response-card" style={{ background: bg, borderLeftColor: color }}>
            <div className="response-card-label" style={{ color }}>
              {icon}
              {label}
            </div>
            <div className="response-card-body">
              <Markdown text={content} />
            </div>
          </div>
        )
      })}
    </div>
  )
}
