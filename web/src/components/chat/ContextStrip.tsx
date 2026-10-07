import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { ProfileState, ProfileSummary } from '../../types'

type Ctx = { p: ProfileState; s: ProfileSummary | null }
let cache: Ctx | null = null // module-level: survives tab switches; refreshed via `refreshKey`

const inr = (n: number) => (n >= 1e7 ? `₹${+(n / 1e7).toFixed(1)}Cr` : n >= 1e5 ? `₹${+(n / 1e5).toFixed(1)}L` : n >= 1e3 ? `₹${Math.round(n / 1e3)}k` : `₹${Math.round(n)}`)

/** Compact "what ARIA knows about you" strip above the composer. Fails silently; height is reserved so nothing shifts. */
export function ContextStrip({ refreshKey, onOpenProfile }: { refreshKey: number; onOpenProfile?: () => void }) {
  const [ctx, setCtx] = useState<Ctx | null>(cache)

  useEffect(() => {
    let live = true
    Promise.all([api.getProfile(), api.getProfileSummary().catch(() => null)])
      .then(([p, s]) => { cache = { p, s }; if (live) setCtx(cache) })
      .catch(() => {})
    return () => { live = false }
  }, [refreshKey])

  if (!ctx) return <div className="context-strip" aria-hidden="true" />
  const { p, s } = ctx
  const income = p.profile.monthly_income
  const surplus = s?.snapshot?.monthly_surplus
  const chips = [
    income != null && `Income ${inr(income)}/mo`,
    surplus != null && `Surplus ${inr(surplus)}`,
    s?.health && s.health.breakdown.some((b) => b.sub !== null) && `Health ${Math.round(s.health.score)}`,
    `Profile ${Math.round(p.completeness.pct)}% complete`,
  ].filter(Boolean) as string[]
  const empty = income == null && !s?.health && p.completeness.pct === 0

  return (
    <div className="context-strip" aria-label="Your context">
      {empty ? (
        <>
          <span>Tell ARIA about yourself once and every answer gets personal</span>
          {onOpenProfile && <button type="button" className="bubble-retry" onClick={onOpenProfile}>Set up profile</button>}
        </>
      ) : (
        <>
          {chips.map((c) => <span key={c} className="context-chip">{c}</span>)}
          {onOpenProfile && <button type="button" className="pf-link btn" onClick={onOpenProfile}>Edit</button>}
        </>
      )}
    </div>
  )
}
