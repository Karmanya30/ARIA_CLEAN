import { AlertTriangle, CheckCircle2, Link2, Lightbulb, BarChart3, Cog } from 'lucide-react'
import { Markdown } from './Markdown'
import './ResponseCard.css'

// Modules 1/3/4 all use this contract. Module 2 uses TAXAL's
// Cognitive/Functional/Causal labels for the same card pattern.
const SECTIONS: Array<[string, React.ReactNode, string, string]> = [
  ['Insight', <Lightbulb size={14} />, 'var(--green)', 'var(--green-soft)'],
  ['Analysis', <BarChart3 size={14} />, 'var(--blue)', 'var(--blue-soft)'],
  ['Recommendation', <CheckCircle2 size={14} />, 'var(--emerald)', 'var(--emerald-soft)'],
  ['Risk', <AlertTriangle size={14} />, 'var(--red)', 'var(--red-soft)'],
]
const TAXAL_SECTIONS: Array<[string, React.ReactNode, string, string]> = [
  ['Cognitive', <Lightbulb size={14} />, 'var(--green)', 'var(--green-soft)'],
  ['Functional', <Cog size={14} />, 'var(--blue)', 'var(--blue-soft)'],
  ['Causal', <Link2 size={14} />, 'var(--amber)', 'var(--amber-soft)'],
]

function parseSections(text: string, labels: string[]): Record<string, string> {
  let normalized = text
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
  const value = String(text ?? '')

  if (value.startsWith('Error:')) {
    return (
      <div className="response-error">
        <p>
          ARIA's language model is temporarily unavailable (both Groq and Gemini failed to
          respond). Any numbers shown separately are still real and computed locally — only the
          narration is missing. Try again in a moment.
        </p>
        <details>
          <summary>Technical details</summary>
          <pre>{value}</pre>
        </details>
      </div>
    )
  }

  let sections = parseSections(
    value,
    SECTIONS.map((s) => s[0]),
  )
  let defs = SECTIONS
  if (Object.keys(sections).length === 0) {
    sections = parseSections(
      value,
      TAXAL_SECTIONS.map((s) => s[0]),
    )
    defs = TAXAL_SECTIONS
  }

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
