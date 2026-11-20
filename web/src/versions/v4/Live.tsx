import { useEffect, useState } from 'react'
import { fmtNum } from '../v2/components/markets/format'
import type { OverviewItem } from '../v2/components/markets/types'

/** Live pieces of the "Pulse" interface. Everything that moves is driven by the real /api/markets/overview data
 * (index prices, how many indices are up); nothing shows an invented number. */

function Spark({ pts, up }: { pts: number[]; up: boolean }) {
  if (pts.length < 2) return null
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1
  const xy = pts.map((v, i) => `${(i / (pts.length - 1)) * 60},${18 - ((v - lo) / span) * 16}`).join(' ')
  return <svg className={`ux4-spark ${up ? 'up' : 'down'}`} viewBox="0 0 60 20" preserveAspectRatio="none" aria-hidden="true"><polyline points={xy} /></svg>
}

/** Scrolling live ribbon of indices under the navigation bar. Prices carry .num, so useNumberFlash flashes them on a change. */
export function LiveRibbon({ items, onOpen }: { items: OverviewItem[]; onOpen: (symbol: string) => void }) {
  if (!items.length) return <div className="ux4-ribbon is-empty"><span>Loading market data…</span></div>
  const row = (hidden: boolean) => <ul aria-hidden={hidden || undefined}>
    {items.map((i) => <li key={i.symbol}>
      <button type="button" tabIndex={hidden ? -1 : undefined} onClick={() => onOpen(i.symbol)} title={`Open ${i.name}`}>
        <b>{i.name}</b>
        <span className="num">{fmtNum(i.price)}</span>
        <em className={i.change_pct >= 0 ? 'up' : 'down'}>{i.change_pct >= 0 ? '▲' : '▼'} {Math.abs(i.change_pct).toFixed(2)}%</em>
        <Spark pts={i.spark ?? []} up={i.change_pct >= 0} />
      </button>
    </li>)}
  </ul>
  return <div className="ux4-ribbon" role="region" aria-label="Live market ribbon"><div className="ux4-ribbon-track">{row(false)}{row(true)}</div></div>
}

/** Ticking IST clock. */
export function IstClock() {
  const [now, setNow] = useState(() => new Date())
  useEffect(() => { const id = setInterval(() => setNow(new Date()), 1000); return () => clearInterval(id) }, [])
  return <span className="ux4-clock num">{now.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata', hour12: false })}</span>
}

/** Market mood gauge: share of Indian indices up today as a ring, plus open/closed. */
export function MoodChip({ items, open, label }: { items: OverviewItem[]; open: boolean | null; label: string }) {
  const up = items.filter((i) => i.change_pct > 0).length
  const share = items.length ? up / items.length : 0.5
  return <div className={`ux4-mood${open ? ' is-open' : ''}`} title={items.length ? `${up} of ${items.length} Indian indices up today · ${label}` : label}>
    <span className="ux4-ring" style={{ '--share': share } as React.CSSProperties} aria-hidden="true"><i /></span>
    <span className="ux4-mood-text"><b>{open === null ? 'Markets' : open ? 'Market open' : 'Market closed'}</b><span><IstClock /> IST</span></span>
    <span className="sr-only">{items.length ? `${up} of ${items.length} Indian indices are up.` : ''}</span>
  </div>
}
