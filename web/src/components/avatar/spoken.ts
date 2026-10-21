/** Turns a written ARIA reply into something that sounds right aloud, and picks the avatar's emotion preset.
 * The backend's ai/llm/spoken.py (POST /api/chat/spoken) does the smart rewrite; this is the offline fallback and the final clean-up. */

const EMOJI = new RegExp('\\p{Extended_Pictographic}|' + String.fromCharCode(0x200d) + '|' + String.fromCharCode(0xfe0f), 'gu')

/** Markdown, tables, links, symbols and money/percent notation to plain speakable sentences. */
export function sanitizeForSpeech(md: string): { text: string; droppedTable: boolean } {
  let droppedTable = false
  const lines = String(md ?? '').replace(/```[\s\S]*?```/g, ' ').split(/\r?\n/).filter((line) => {
    const isTable = (line.match(/\|/g)?.length ?? 0) >= 2 || (/^\s*[:\-| ]{3,}$/.test(line) && line.includes('-'))
    if (isTable) droppedTable = true
    return !isTable && !/^\s*([-*_]\s*){3,}$/.test(line)
  })
  const t = lines.map((l) => {
    let s = l.replace(/^\s*(#{1,6}|>|[-*+•]|\d+[.)])\s+/, '').trim()
    if (s && !/[.!?:;,]$/.test(s)) s += '.' // headings and bullets end their own sentence
    return s
  }).join(' ')
    .replace(/!\[[^\]]*\]\([^)]*\)/g, ' ')
    .replace(/\[([^\]]+)\]\([^)]*\)/g, '$1')
    .replace(/https?:\/\/\S+/g, ' ')
    .replace(/`([^`]*)`/g, '$1')
    .replace(/[*_~]{1,3}([^*_~]+)[*_~]{1,3}/g, '$1')
    .replace(/\b(Insight|Analysis|Recommendation|Risk|Sources?|Disclaimer)\s*:\s*/gi, '')
    .replace(EMOJI, '')
    .replace(/(?:₹|\bRs\.?|\bINR)\s?(\d[\d,]*(?:\.\d+)?)(\s?(?:lakh|lakhs|crore|crores|k|thousand|million|billion))?/gi,
      (_m, n: string, unit?: string) => `${n}${unit ?? ''} rupees`)
    .replace(/\$\s?(\d[\d,]*(?:\.\d+)?)(\s?(?:k|thousand|million|billion))?/gi,
      (_m, n: string, unit?: string) => `${n}${unit ?? ''} dollars`)
    .replace(/(\d)\s?%/g, '$1 percent')
    .replace(/\s*(?:->|→)\s*/g, ' to ')
    .replace(/≥/g, ' at least ').replace(/≤/g, ' at most ').replace(/~(?=\d)/g, 'about ')
    .replace(/\s&\s/g, ' and ')
    .replace(/[*_#>|]/g, ' ')
    .replace(/\.\s*\./g, '.').replace(/([:;,])\./g, '.')
    .replace(/\s+/g, ' ')
    .trim()
  return { text: t, droppedTable }
}

/** A short spoken version: the first sentences up to about `maxWords`, with a pointer to the screen when anything was cut. */
export function conciseSpoken(md: string, maxWords = 70): string {
  const { text, droppedTable } = sanitizeForSpeech(md)
  if (!text) return ''
  const sentences = text.match(/[^.!?]+[.!?]+(?:\s|$)|[^.!?]+$/g) ?? [text]
  const kept: string[] = []
  let words = 0
  for (const s of sentences) {
    const n = s.trim().split(/\s+/).length
    if (kept.length && words + n > maxWords) break
    kept.push(s.trim())
    words += n
  }
  const cut = kept.length < sentences.length || droppedTable
  return kept.join(' ') + (cut ? ' The full details are on screen.' : '')
}

export interface EmotionHint { emotion: string; style?: { rate: number } }
interface ReplyLike { domain?: string; response?: string; tone?: { strategy?: string } }

/** Reply tone/domain from the chat response when present; otherwise a light wording heuristic. The engine's presets are
 * neutral | warm | serious | concerned | upbeat; style.rate is the speaking-rate multiplier. */
export function emotionFor(reply: ReplyLike): EmotionHint {
  const strategy = reply.tone?.strategy
  if (reply.domain === 'care' || strategy === 'care' || strategy === 'reassure' || strategy === 'listen') return { emotion: 'concerned', style: { rate: 0.92 } }
  if (reply.domain === 'error') return { emotion: 'concerned', style: { rate: 0.92 } }
  const text = reply.response ?? ''
  if (/\b(sorry|unfortunately|struggl|stress|worried|can't afford|not possible)\b/i.test(text)) return { emotion: 'concerned', style: { rate: 0.92 } }
  if (/\b(congrat|great news|well done|you're on track|on track|excellent)\b/i.test(text)) return { emotion: 'upbeat' }
  if (/\b(high risk|warning|caution|risky|default|penalt|loss of)\b/i.test(text)) return { emotion: 'serious', style: { rate: 0.95 } }
  return { emotion: 'warm' }
}
