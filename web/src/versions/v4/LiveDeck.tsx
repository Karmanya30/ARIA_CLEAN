import { useEffect, useRef, useState } from 'react'
import { Maximize2 } from 'lucide-react'
import { useMarket } from '../v2/hooks/useMarket'
import { fmtNum } from '../v2/components/markets/format'
import { MarketStatusBar } from '../v2/components/markets/MarketStatusBar'
import type { Chart, Overview, OverviewItem } from '../v2/components/markets/types'

/** Pulse's live head for the Markets page (option 1 of the effect lab): index tiles that count up and flash on every
 * change, and a large chart of the selected index that draws itself in, with a crosshair. Real /api/markets data only.
 * The Classic Markets sections (movers, sectors, news, watchlist) follow underneath. */
const REDUCE = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const GROUPS = [['india', 'India'], ['global', 'Global'], ['fx', 'Currency'], ['commodity', 'Commodities'], ['crypto', 'Crypto']] as const
const RANGES = ['1D', '5D', '1M', '6M', '1Y'] as const
const greeting = () => { const h = Number(new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', hour: 'numeric', hour12: false })); return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening' }

/** Counts up from 0 the first time a value appears, then shows the live value (useNumberFlash flashes later changes). */
function CountUp({ value, digits = 2 }: { value: number; digits?: number }) {
  const [shown, setShown] = useState<number | null>(REDUCE ? null : 0)
  const done = useRef(REDUCE)
  useEffect(() => {
    if (done.current) return
    const t0 = performance.now()
    let raf = 0
    const f = (t: number) => {
      const p = Math.min(1, (t - t0) / 1200)
      if (p < 1) { setShown(value * (1 - (1 - p) ** 3)); raf = requestAnimationFrame(f) } else { done.current = true; setShown(null) }
    }
    raf = requestAnimationFrame(f)
    return () => cancelAnimationFrame(raf)
  }, [value])
  return <span className="num">{fmtNum(shown ?? value, digits)}</span>
}

function Spark({ pts, up }: { pts: number[]; up: boolean }) {
  if (pts.length < 2) return <svg className="ux4-kpi-spark" aria-hidden="true" />
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1
  const xy = pts.map((v, i) => `${(i / (pts.length - 1)) * 100},${38 - ((v - lo) / span) * 34}`)
  return <svg className={`ux4-kpi-spark ${up ? 'up' : 'down'}`} viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true">
    <polygon points={`0,40 ${xy.join(' ')} 100,40`} /><polyline points={xy.join(' ')} />
  </svg>
}

function Kpi({ item, active, onPick }: { item: OverviewItem; active: boolean; onPick: () => void }) {
  const up = item.change_pct >= 0
  return <button type="button" className={`ux4-kpi${active ? ' is-active' : ''}`} onClick={onPick} aria-pressed={active}>
    <span className="ux4-kpi-name">{item.name}</span>
    <b className="ux4-kpi-price"><CountUp value={item.price} /></b>
    <em className={up ? 'up' : 'down'}>{up ? '▲' : '▼'} {Math.abs(item.change_pct).toFixed(2)}% <span className="num">({up ? '+' : '−'}{fmtNum(Math.abs(item.change))})</span></em>
    <Spark pts={item.spark ?? []} up={up} />
  </button>
}

function BigChart({ item, onDetails }: { item: OverviewItem; onDetails: () => void }) {
  const [range, setRange] = useState<(typeof RANGES)[number]>('1D')
  const intraday = range === '1D' || range === '5D'
  const ch = useMarket<Chart>(`/api/markets/chart?symbol=${encodeURIComponent(item.symbol)}&range=${range}`, intraday ? 60_000 : 3_600_000)
  const bars = ch.data?.symbol === item.symbol && ch.data.range === range ? ch.data.bars : null
  const [hover, setHover] = useState<number | null>(null)
  const W = 1000, H = 300
  const closes = bars?.map((b) => b.c) ?? []
  const lo = Math.min(...closes), hi = Math.max(...closes), pad = (hi - lo) * 0.08 || 1
  const x = (i: number) => (i / Math.max(1, closes.length - 1)) * W
  const y = (v: number) => H - ((v - lo + pad) / (hi - lo + pad * 2)) * H
  const line = closes.map((v, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join('')
  const first = closes[0], last = closes[closes.length - 1]
  const up = closes.length > 1 ? last >= first : item.change_pct >= 0
  const when = (t: number) => new Date(t * 1000).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', ...(intraday ? { hour: '2-digit', minute: '2-digit', day: range === '5D' ? 'numeric' : undefined, month: range === '5D' ? 'short' : undefined } : { day: 'numeric', month: 'short', year: '2-digit' }) })
  const hb = hover !== null && bars ? bars[hover] : null

  return <section className={`ux4-chart ${up ? 'up' : 'down'}`} aria-label={`${item.name} chart`}>
    <header>
      <div>
        <span className="ux4-chart-name">{item.name}</span>
        <div className="ux4-chart-price">
          <b className="num">{fmtNum(hb ? hb.c : item.price)}</b>
          {closes.length > 1 && !hb && <em className={up ? 'up' : 'down'}>{up ? '▲' : '▼'} {Math.abs((last / first - 1) * 100).toFixed(2)}% <small>over {range}</small></em>}
          {hb && <em className="ux4-chart-when">{when(hb.t)}</em>}
        </div>
      </div>
      <div className="ux4-chart-tools">
        <div className="ux4-seg" role="group" aria-label="Chart range">
          {RANGES.map((r) => <button key={r} type="button" aria-pressed={range === r} onClick={() => { setRange(r); setHover(null) }}>{r}</button>)}
        </div>
        <button type="button" className="ux4-icon" onClick={onDetails} aria-label={`Open ${item.name} details`} title="Details"><Maximize2 size={16} aria-hidden="true" /></button>
      </div>
    </header>
    <div className="ux4-chart-plot">
      {closes.length > 1 ? (
        <svg key={`${item.symbol}-${range}`} viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img" aria-label={`${item.name}, ${range}, from ${fmtNum(first)} to ${fmtNum(last)}`}
          onPointerMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(closes.length - 1, Math.round(((e.clientX - r.left) / r.width) * (closes.length - 1))))) }}
          onPointerLeave={() => setHover(null)}>
          <defs>
            <linearGradient id="ux4-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="currentColor" stopOpacity="0.28" /><stop offset="1" stopColor="currentColor" stopOpacity="0" /></linearGradient>
          </defs>
          {[0.25, 0.5, 0.75].map((g) => <line key={g} className="grid" x1="0" x2={W} y1={H * g} y2={H * g} />)}
          <path className="area" d={`${line}L${W},${H}L0,${H}Z`} />
          <path className="ln" d={line} pathLength={1} />
          {first !== undefined && <line className="base" x1="0" x2={W} y1={y(first)} y2={y(first)} />}
          {hb && hover !== null && <g className="xh">
            <line x1={x(hover)} x2={x(hover)} y1="0" y2={H} /><line x1="0" x2={W} y1={y(hb.c)} y2={y(hb.c)} />
            <circle cx={x(hover)} cy={y(hb.c)} r="5" />
          </g>}
        </svg>
      ) : <p className="ux4-chart-empty">{ch.error ? 'The chart is unavailable right now.' : 'Loading chart…'}</p>}
    </div>
  </section>
}

export function LiveDeck({ onDetails }: { onDetails: (symbol: string) => void }) {
  const ov = useMarket<Overview>('/api/markets/overview', 30_000)
  const [group, setGroup] = useState<(typeof GROUPS)[number][0]>('india')
  const [pick, setPick] = useState<string | null>(null)
  const items = ov.data?.items.filter((i) => i.group === group) ?? []
  const sel = items.find((i) => i.symbol === pick) ?? items[0]
  return <div className="ux4-deck">
    <header className="ux4-deck-head">
      <div>
        <h1>Markets</h1>
        <p>{greeting()}. Here is the market right now.</p>
      </div>
      <MarketStatusBar ov={ov.data} error={ov.error} />
    </header>
    <div className="ux4-seg ux4-groups" role="group" aria-label="Index group">
      {GROUPS.map(([id, l]) => <button key={id} type="button" aria-pressed={group === id} onClick={() => { setGroup(id); setPick(null) }}>{l}</button>)}
    </div>
    <div className="ux4-kpis">
      {ov.data
        ? items.map((i) => <Kpi key={i.symbol} item={i} active={i.symbol === sel?.symbol} onPick={() => setPick(i.symbol)} />)
        : [0, 1, 2, 3].map((k) => <div key={k} className="ux4-kpi is-skel" aria-hidden="true" />)}
      {ov.data && !items.length && <p className="ux4-chart-empty">No data for this group yet.</p>}
      {ov.error && !ov.data && <p className="ux4-chart-empty">Indices are unavailable right now.</p>}
    </div>
    {sel && <BigChart key={sel.symbol} item={sel} onDetails={() => onDetails(sel.symbol)} />}
  </div>
}
