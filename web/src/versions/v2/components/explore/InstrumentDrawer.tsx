import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { instrumentPaths } from '../../api'
import { useMarket } from '../../hooks/useMarket'
import type { InstrumentChart, InstrumentProfile, InstrumentQuote, InstrumentRange } from '../../types'
import { Delta } from '../markets/Delta'
import { fmtIst, fmtNum } from '../markets/format'
import { Provenance } from '../markets/Provenance'
import '../markets/panels.css'
import { AskPanel } from './AskPanel'
import { cleanPoints, LineChart } from './LineChart'
import { SipPanel } from './SipPanel'
import { fmtMoney, priceLabel, readIxWatchlist, toggleIxWatch, typeLabel } from './instruments'
import './explore.css'

const RANGES: { id: InstrumentRange; label: string }[] = [
  { id: '1d', label: '1D' },
  { id: '5d', label: '5D' },
  { id: '1m', label: '1M' },
  { id: '6m', label: '6M' },
  { id: '1y', label: '1Y' },
  { id: '5y', label: '5Y' },
  { id: 'max', label: 'Max' },
]

/** Typical risks to show when the API's profile has no risk tags of its own. */
const TYPICAL_RISK: Record<string, string[]> = {
  stock: ['Market risk', 'Company-specific risk'],
  mf: ['Subject to market risk', 'Returns not guaranteed'],
  etf: ['Market risk', 'Tracking error'],
  crypto: ['Extremely volatile', 'Largely unregulated'],
  bond: ['Interest-rate risk', 'Credit risk'],
  index: ['Not directly investable'],
  commodity: ['Price swings', 'Global events'],
  currency: ['Exchange-rate risk'],
}

const FACTS: [string, string, 'num' | 'compact' | 'pct' | 'text'][] = [
  ['prev_close', 'Previous close', 'num'], ['day_low', 'Day low', 'num'], ['day_high', 'Day high', 'num'],
  ['year_low', '52-week low', 'num'], ['year_high', '52-week high', 'num'], ['volume', 'Volume', 'compact'],
  ['market_cap', 'Market cap', 'compact'], ['pe', 'P/E', 'num'], ['sector', 'Sector', 'text'], ['category', 'Category', 'text'],
  ['fund_house', 'Fund house', 'text'], ['aum', 'AUM', 'compact'], ['expense_ratio', 'Expense ratio', 'pct'], ['yield', 'Yield', 'pct'],
  ['exchange', 'Exchange', 'text'],
]
const compact = new Intl.NumberFormat('en-IN', { notation: 'compact', maximumFractionDigits: 2 })
const human = (k: string) => k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
function showFact(v: string | number, kind: string): string {
  if (typeof v === 'string') return v
  return kind === 'compact' ? compact.format(v) : kind === 'pct' ? `${fmtNum(v)}%` : fmtNum(v, Math.abs(v) >= 1000 ? 0 : 2)
}

function collectFacts(q: InstrumentQuote, p: InstrumentProfile | null): [string, string][] {
  const out = new Map<string, string>()
  for (const [key, label, kind] of FACTS) {
    const v = q[key]
    if ((typeof v === 'number' && Number.isFinite(v)) || (typeof v === 'string' && v)) out.set(label, showFact(v as string | number, kind))
  }
  for (const [k, v] of Object.entries(q.facts ?? {})) if (v != null && v !== '') out.set(human(k), showFact(v, 'num'))
  const st = p?.stats
  if (Array.isArray(st)) for (const s of st) s?.label && s.value != null && s.value !== '' && out.set(s.label, showFact(s.value, 'num'))
  else if (st) for (const [k, v] of Object.entries(st)) v != null && v !== '' && out.set(human(k), showFact(v, 'num'))
  return [...out].slice(0, 16)
}

const skel = (h: string, w?: number) => <span className="mk-skel" style={{ '--h': h, ...(w ? { width: w } : {}) } as React.CSSProperties} />

function Drawer({ id, sessionId, onClose, onDisclaimers }: { id: string; sessionId: string; onClose: () => void; onDisclaimers: () => void }) {
  const dlg = useRef<HTMLDialogElement>(null)
  const [range, setRange] = useState<InstrumentRange>('1y')
  const [tip, setTip] = useState<string | null>(null)
  const [wl, setWl] = useState(() => readIxWatchlist().includes(id))
  const [retry, setRetry] = useState(0)
  const bust = retry ? `&_=${retry}` : ''
  const intraday = range === '1d' || range === '5d'
  const q = useMarket<InstrumentQuote>(`${instrumentPaths.quote(id)}${retry ? `?_=${retry}` : ''}`, 60_000)
  const ch = useMarket<InstrumentChart>(`${instrumentPaths.chart(id, range)}${bust}`, intraday ? 60_000 : 3_600_000)
  const pf = useMarket<InstrumentProfile>(instrumentPaths.profile(id), 0)

  useEffect(() => {
    const d = dlg.current!
    const opener = document.activeElement as HTMLElement | null
    d.showModal()
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = prev
      d.close()
      opener?.focus?.()
    }
  }, [])
  useEffect(() => {
    const sync = () => setWl(readIxWatchlist().includes(id))
    window.addEventListener('aria-watchlist', sync)
    window.addEventListener('storage', sync)
    return () => (window.removeEventListener('aria-watchlist', sync), window.removeEventListener('storage', sync))
  }, [id])
  const onTip = useCallback((t: string | null) => setTip(t), [])

  const quote = q.data
  const type = quote?.type ?? (id.split(':')[0] as InstrumentQuote['type'])
  const pts = ch.data?.points ?? null
  const profile = pf.data
  const facts = useMemo(() => (quote ? collectFacts(quote, profile) : []), [quote, profile])
  const rows = useMemo(() => cleanPoints(pts ?? []).slice(-30), [pts])
  const tags = (profile?.risk_tags ?? []).map((t) => (typeof t === 'string' ? t : t?.label)).filter(Boolean) as string[]
  const riskTags = tags.length ? tags : TYPICAL_RISK[type] ?? []
  const desc = profile?.description ?? profile?.summary
  const rowFmt = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', ...(intraday ? { hour: '2-digit', minute: '2-digit', hour12: false } : {}) })
  const chartNote = ch.data?.meta?.note

  return (
    <dialog ref={dlg} className="sd ix-drawer" aria-labelledby="ix-title" onCancel={(e) => (e.preventDefault(), onClose())} onClick={(e) => e.target === dlg.current && onClose()}>
      <div className="sd-body">
        <div className="sd-head">
          <div>
            <h2 id="ix-title">{quote?.name ?? id.slice(id.indexOf(':') + 1)}</h2>
            <span className="sd-sym">
              {[id.slice(id.indexOf(':') + 1), typeLabel(type), quote?.currency].filter(Boolean).join(' · ')}
            </span>
          </div>
          <button className="sd-x" type="button" onClick={onClose} aria-label="Close details">✕</button>
        </div>

        <div className="sd-price" aria-live="polite">
          {quote ? (
            <>
              <span className="ix-pl">{priceLabel(type)}</span>
              <span className="big num">{fmtMoney(quote.price, quote.currency)}</span>
              {quote.change != null && <Delta value={quote.change} suffix="" />}
              {quote.change_pct != null && <Delta value={quote.change_pct} />}
            </>
          ) : q.error ? (
            <span className="note">
              We could not load this instrument right now. <button type="button" className="ix-link" onClick={() => setRetry((n) => n + 1)}>Try again</button>
            </span>
          ) : (
            skel('36px', 220)
          )}
        </div>
        <div className="ix-prov">
          {quote && (
            <>
              <Provenance kind="data" source={quote.source ?? undefined} asOf={quote.as_of ? fmtIst(quote.as_of) : undefined} />
              {quote.delay_note && <span className="mk-chip">{quote.delay_note}</span>}
              {quote.stale && <span className="mk-chip ix-warn">Stale: showing the last value ARIA could fetch</span>}
            </>
          )}
        </div>

        {riskTags.length > 0 && (
          <ul className="ix-risks" aria-label={tags.length ? 'Risk tags' : 'Typical risks for this kind of instrument'}>
            {riskTags.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        )}
        {desc ? <p className="ix-desc">{desc}</p> : pf.loading ? skel('48px') : null}

        <div className="sd-bar">
          <div className="seg" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button key={r.id} type="button" aria-pressed={range === r.id} onClick={() => (setRange(r.id), setTip(null))}>{r.label}</button>
            ))}
          </div>
        </div>
        <div className="sd-chart-wrap">
          {pts && pts.length > 1 ? (
            <LineChart points={pts} intraday={intraday} onTip={onTip} label={`${quote?.name ?? id} ${priceLabel(type).toLowerCase()} chart, ${pts.length} points. A table version follows.`} />
          ) : ch.error || pts ? (
            <div className="sd-fail">
              <span>{chartNote || (pts ? 'No history for this range' : 'Chart unavailable right now')}</span>
              <button className="btn" type="button" onClick={() => setRetry((n) => n + 1)}>Retry</button>
            </div>
          ) : (
            skel('100%')
          )}
        </div>
        <div className="sd-tip">{tip ?? 'Move over or touch the chart to read a point.'}</div>
        {ch.data?.meta?.source && <div className="ix-prov"><Provenance kind="data" source={String(ch.data.meta.source)} /></div>}
        {rows.length > 0 && (
          <details>
            <summary>View data as table</summary>
            <div className="sd-scroll">
              <table>
                <caption className="sr-only">Last {rows.length} points</caption>
                <thead><tr><th scope="col">Date</th><th scope="col">{priceLabel(type)}</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.time} className="num"><td>{rowFmt.format(new Date(r.time * 1000))}</td><td>{fmtNum(r.value)}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}

        {facts.length > 0 ? (
          <dl className="sd-stats num" aria-label="Key facts">
            {facts.map(([k, v]) => (
              <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        ) : quote ? (
          <p className="note">ARIA has no further facts for this instrument yet.</p>
        ) : null}

        <SipPanel id={id} />

        <div className="sd-actions">
          <button className="btn" type="button" aria-pressed={wl} onClick={() => toggleIxWatch(id)}>
            {wl ? '★ In your watchlist (remove)' : '☆ Add to watchlist'}
          </button>
        </div>

        {quote ? (
          <AskPanel quote={quote} sessionId={sessionId} onDisclaimers={() => (onClose(), onDisclaimers())} />
        ) : (
          skel('120px')
        )}
      </div>
    </dialog>
  )
}

/** Detail drawer for any instrument (stock, fund, ETF, coin, bond, index, commodity, currency): price, chart, facts, SIP simulation and an Ask-ARIA chat. */
export function InstrumentDrawer({ id, sessionId, onClose, onDisclaimers }: { id: string | null; sessionId: string; onClose: () => void; onDisclaimers: () => void }) {
  return id ? <Drawer key={id} id={id} sessionId={sessionId} onClose={onClose} onDisclaimers={onDisclaimers} /> : null
}
