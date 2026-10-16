import { fmtIst } from './format'
import type { Overview } from './types'

export function MarketStatusBar({ ov, error }: { ov: Overview | null; error: string | null }) {
  if (!ov) return <div className="mk-status" role="status">{error ? <span className="mk-chip">Market status unavailable</span> : <span className="mk-skel" style={{ width: 220, ['--h' as string]: '28px' }} />}</div>
  const s = ov.status
  return (
    <div className="mk-status" role="status">
      <span className={`mk-pill ${s.open ? 'is-open' : ''}`}><span className="mk-dot" aria-hidden="true" />{s.label}</span>
      <span className="mk-chip num">{fmtIst(s.now_ist)}</span>
      <span className="mk-chip">Data delayed ~{ov.meta.delay_min} min</span>
      {ov.meta.stale && <span className="mk-chip mk-warn">Stale, last updated {fmtIst(ov.meta.as_of)}</span>}
      {s.note && <span className="mk-faint">{s.note}</span>}
    </div>
  )
}
