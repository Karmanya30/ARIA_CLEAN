import type { ChatResponse } from '../../types'
import '../research/IntelligenceTab.css'

type Pillar = { name: string; rating: string }
type Flag = { id: string; severity: string; text: string }
const scoreColour = (s: number) => (s >= 70 ? 'var(--green)' : s >= 45 ? 'var(--amber)' : 'var(--red)')
const ratingColour = (r: string) => (r === 'strong' ? 'var(--green)' : r === 'weak' ? 'var(--red)' : r === 'mixed' ? 'var(--amber)' : 'var(--ink-faint)')

/** The score, the pillars and any disagreements, under the spoken answer in chat. The full breakdown lives in the Company intelligence tab. */
export function IntelligenceSummary({ data }: { data: ChatResponse }) {
  const i = data.intelligence as { score: number; divergences: Flag[] } | undefined
  const pillars = (data.scorecard as { pillars?: Pillar[] } | undefined)?.pillars ?? []
  if (!i || typeof i.score !== 'number') return null
  return (
    <div className="ri-hero" style={{ padding: 14, gap: 16, boxShadow: 'none', marginTop: 8 }}>
      <div className="ri-ring" style={{ ['--p' as string]: i.score, ['--c' as string]: scoreColour(i.score), width: 76, height: 76 }} role="img" aria-label={`Score ${Math.round(i.score)} out of 100`}>
        <span style={{ fontSize: 24 }}>{Math.round(i.score)}</span>
      </div>
      <div className="ri-hero-text">
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {pillars.map((p) => <span key={p.name} className="ri-pill" style={{ background: ratingColour(p.rating) }}>{p.name} · {p.rating === 'n/a' ? 'no data' : p.rating}</span>)}
        </div>
        {i.divergences.slice(0, 2).map((d) => <p key={d.id} className="ri-sub" style={{ margin: '6px 0 0' }}>⚑ {d.text}</p>)}
        <p className="ri-sub" style={{ margin: '6px 0 0' }}>Full breakdown: Company intelligence tab.</p>
      </div>
    </div>
  )
}
