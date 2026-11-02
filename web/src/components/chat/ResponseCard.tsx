import { Markdown } from './Markdown'
import './ResponseCard.css'

// Modules 1/3/4 all use this contract.
const SECTIONS = ['Insight', 'Analysis', 'Recommendation', 'Risk']

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

  // Older and deterministic replies are written as "Insight: ... Analysis: ... Recommendation: ... Risk: ...". They are shown as plain
  // Markdown in that order, without the labels or coloured boxes, like every other answer.
  const labelled = /^\s*\**Insight\**\s*:/i.test(value) // only text that starts in that format; an ordinary answer is never rewritten
  const sections = labelled ? parseSections(value, SECTIONS) : {}
  const parts = SECTIONS.map((label) => sections[label]).filter(Boolean)

  return (
    <div className="response-plain">
      <Markdown text={parts.length ? parts.join('\n\n') : value} />
    </div>
  )
}
