import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { IChartApi } from 'lightweight-charts'
import { api, type CompanyIntel } from '../../api'
import { useMarket } from '../../hooks/useMarket'
import { SipPanel } from '../explore/SipPanel'
import { Delta } from './Delta'
import { Provenance } from './Provenance'
import { Ring } from './charts'
import { fmtCr, fmtInr, fmtNum } from './format'
import type { Chart, Quote } from './types'
import './panels.css'

const RANGES = ['1D', '5D', '1M', '6M', '1Y', '5Y'] as const
const WL_KEY = 'aria_watchlist'
const IST = 'Asia/Kolkata'

function readWatchlist(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(WL_KEY) || '[]')
    return Array.isArray(v) ? v.filter((s) => typeof s === 'string') : []
  } catch {
    return []
  }
}
function toggleWatch(sym: string) {
  const list = readWatchlist()
  const next = list.includes(sym) ? list.filter((s) => s !== sym) : [...list, sym]
  try {
    localStorage.setItem(WL_KEY, JSON.stringify(next))
  } catch {
    /* storage blocked: the star just will not persist */
  }
  window.dispatchEvent(new Event('aria-watchlist'))
}

const istFmt = (intraday: boolean) =>
  new Intl.DateTimeFormat('en-IN', {
    timeZone: IST,
    day: '2-digit',
    month: 'short',
    ...(intraday ? { hour: '2-digit', minute: '2-digit', hour12: false } : { year: 'numeric' }),
  })

const withAlpha = (c: string, a: string) => (/^#[0-9a-f]{6}$/i.test(c) ? c + a : c)

/** Marker on a low..high line. The values are in the label, so position never relies on colour. */
function RangeBar({ title, low, high, value }: { title: string; low: number; high: number; value: number }) {
  const pos = high > low ? Math.max(0, Math.min(1, (value - low) / (high - low))) : 0.5
  const x = 6 + pos * 188
  return (
    <svg
      className="sd-range"
      viewBox="0 0 200 52"
      width="100%"
      role="img"
      aria-label={`${title}: low ${fmtNum(low)}, high ${fmtNum(high)}, now ${fmtNum(value)}, ${Math.round(pos * 100)}% of the way up`}
    >
      <text x="0" y="10">{title}</text>
      <line x1="6" x2="194" y1="34" y2="34" stroke="var(--border-strong)" strokeWidth="4" strokeLinecap="round" />
      <line x1="6" x2={x} y1="34" y2="34" stroke="var(--accent)" strokeWidth="4" strokeLinecap="round" />
      <path d={`M${x} 27l5 -8h-10z`} fill="var(--ink)" />
      <text x="0" y="50">{fmtNum(low, 0)}</text>
      <text x="200" y="50" textAnchor="end">{fmtNum(high, 0)}</text>
    </svg>
  )
}

function PriceChart({ bars, mode, intraday, onTip }: { bars: Chart['bars']; mode: 'area' | 'candles'; intraday: boolean; onTip: (t: React.ReactNode) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  // Colours are read from CSS variables at build time, so rebuild when Light/Night flips (ponytail: loses zoom, fine).
  const [modeTick, setModeTick] = useState(0)
  useEffect(() => {
    const mo = new MutationObserver(() => setModeTick((n) => n + 1))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-mode'] })
    return () => mo.disconnect()
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el) return
    let chart: IChartApi | undefined
    let ro: ResizeObserver | undefined
    let dead = false
    const fmt = istFmt(intraday)
    const timeFmt = (t: number) => fmt.format(new Date(t * 1000))
    import('lightweight-charts').then(({ createChart, AreaSeries, CandlestickSeries, HistogramSeries, ColorType }) => {
      if (dead) return
      const cs = getComputedStyle(el)
      const v = (n: string) => cs.getPropertyValue(n).trim()
      const [up, down, ink, border, bg] = [v('--up'), v('--down'), v('--ink-muted'), v('--border'), v('--bg')]
      const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      chart = createChart(el, {
        autoSize: false,
        width: el.clientWidth,
        height: el.clientHeight,
        layout: { background: { type: ColorType.Solid, color: bg }, textColor: ink, attributionLogo: true, fontSize: 11 },
        grid: { vertLines: { color: border }, horzLines: { color: border } },
        rightPriceScale: { borderColor: border },
        timeScale: { borderColor: border, timeVisible: intraday, tickMarkFormatter: (t: number) => timeFmt(t) },
        localization: { timeFormatter: timeFmt },
        kineticScroll: { mouse: !calm, touch: !calm },
      })
      const data = bars.filter((b, i) => i === 0 || b.t > bars[i - 1].t)
      const rising = data.length < 2 || data[data.length - 1].c >= data[0].c
      const line = rising ? up : down
      const main =
        mode === 'candles'
          ? chart.addSeries(CandlestickSeries, { upColor: up, downColor: down, borderUpColor: up, borderDownColor: down, wickUpColor: up, wickDownColor: down })
          : chart.addSeries(AreaSeries, { lineColor: line, topColor: withAlpha(line, '40'), bottomColor: withAlpha(line, '05'), lineWidth: 2 })
      main.setData(
        (mode === 'candles'
          ? data.map((b) => ({ time: b.t, open: b.o, high: b.h, low: b.l, close: b.c }))
          : data.map((b) => ({ time: b.t, value: b.c }))) as never,
      )
      main.priceScale().applyOptions({ scaleMargins: { top: 0.08, bottom: 0.28 } })
      const vol = chart.addSeries(HistogramSeries, { priceScaleId: '', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false })
      vol.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } })
      vol.setData(data.map((b) => ({ time: b.t, value: b.v, color: withAlpha(b.c >= b.o ? up : down, '80') })) as never)
      chart.timeScale().fitContent()
      const byT = new Map(data.map((b) => [b.t, b]))
      chart.subscribeCrosshairMove((p) => {
        const b = p.time !== undefined ? byT.get(p.time as number) : undefined
        if (!b) return onTip(null)
        onTip(
          <>
            <b>{timeFmt(b.t)}{intraday ? ' IST' : ''}</b> · O {fmtNum(b.o)} H {fmtNum(b.h)} L {fmtNum(b.l)} C <b>{fmtNum(b.c)}</b> · Vol {b.v.toLocaleString('en-IN')}
          </>,
        )
      })
      ro = new ResizeObserver(() => chart?.resize(el.clientWidth, el.clientHeight))
      ro.observe(el)
    })
    return () => {
      dead = true
      ro?.disconnect()
      chart?.remove()
    }
  }, [bars, mode, intraday, onTip, modeTick])
  const last = bars[bars.length - 1]
  return <div ref={ref} className="sd-chart" role="img" aria-label={`Price chart, ${bars.length} points, last close ${last ? fmtNum(last.c) : 'n/a'}. A table version follows.`} />
}

function Intel({ symbol, onChat }: { symbol: string; onChat: () => void }) {
  const [st, setSt] = useState<{ s: 'idle' | 'load' | 'err'; d?: CompanyIntel }>({ s: 'idle' })
  const run = () => {
    setSt({ s: 'load' })
    api.companyIntel(symbol.replace(/\.(NS|BO)$/i, '')).then(
      (d) => setSt({ s: 'idle', d }),
      () => setSt({ s: 'err' }),
    )
  }
  const i = st.d?.intelligence
  const top = i?.divergences?.[0]
  return (
    <section className="mk-card" aria-live="polite" aria-busy={st.s === 'load'} style={{ display: 'grid', gap: 'var(--s-3)' }}>
      <div className="sd-h"><h3>ARIA intelligence score</h3><Provenance kind="ai" /></div>
      {i ? (
        <div className="sd-intel">
          <Ring value={i.score} label={`Intelligence score ${Math.round(i.score)} out of 100, ${i.band}`}>
            <text x="48" y="56" textAnchor="middle" style={{ fontSize: 24, fontWeight: 650, fill: 'var(--ink)' }}>{Math.round(i.score)}</text>
          </Ring>
          <div>
            <strong>{i.band}</strong>
            {top && <p className="note">Top divergence: {top.text}</p>}
            {i.low_evidence && <p className="note">Low evidence, treat as provisional.</p>}
            <button className="btn" type="button" onClick={onChat} style={{ marginTop: 'var(--s-2)' }}>Open the full read in chat</button>
          </div>
        </div>
      ) : (
        <>
          <p className="note">Combines fundamentals, news tone and management commentary. Takes about 15 seconds.</p>
          <button className="btn primary" type="button" onClick={run} disabled={st.s === 'load'}>
            {st.s === 'load' ? 'Scoring, about 15 seconds…' : st.s === 'err' ? 'Could not score. Try again' : 'Get ARIA intelligence score'}
          </button>
        </>
      )}
    </section>
  )
}

const skel = (h: string, w?: number) => <span className="mk-skel" style={{ '--h': h, ...(w ? { width: w } : {}) } as React.CSSProperties} />

function Drawer({ symbol, onClose, onAsk }: { symbol: string; onClose: () => void; onAsk: (q: string) => void }) {
  const dlg = useRef<HTMLDialogElement>(null)
  const [range, setRange] = useState<(typeof RANGES)[number]>('1Y')
  const [mode, setMode] = useState<'area' | 'candles'>('area')
  const [tip, setTip] = useState<React.ReactNode>(null)
  const [wl, setWl] = useState(() => readWatchlist().includes(symbol))
  const [retry, setRetry] = useState(0)
  const q = useMarket<Quote>(`/api/markets/quote?symbol=${encodeURIComponent(symbol)}`, 60000)
  const intraday = range === '1D' || range === '5D'
  // 1 h instead of 0: useMarket would refetch in a tight loop with a zero interval
  const ch = useMarket<Chart>(`/api/markets/chart?symbol=${encodeURIComponent(symbol)}&range=${range}${retry ? `&_=${retry}` : ''}`, intraday ? 60000 : 3600000)

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
    const sync = () => setWl(readWatchlist().includes(symbol))
    window.addEventListener('aria-watchlist', sync)
    window.addEventListener('storage', sync)
    return () => (window.removeEventListener('aria-watchlist', sync), window.removeEventListener('storage', sync))
  }, [symbol])

  const onTip = useCallback((t: React.ReactNode) => setTip(t), [])
  const quote = q.data
  const bars = ch.data?.symbol === symbol && ch.data.range === range ? ch.data.bars : null
  const name = quote?.name ?? symbol
  const pct = quote?.change_pct ?? 0
  const ask = (text: string) => {
    onAsk(text)
    onClose()
  }
  const rows = useMemo(() => (bars ?? []).slice(-30), [bars])
  const rowFmt = istFmt(intraday)
  const m = quote?.meta
  const dir = pct < 0 ? 'down' : 'up'

  return (
    <dialog
      ref={dlg}
      className="sd"
      aria-labelledby="sd-title"
      onCancel={(e) => (e.preventDefault(), onClose())}
      onClick={(e) => e.target === dlg.current && onClose()}
    >
      <div className="sd-body">
        <div className="sd-head">
          <div>
            <h2 id="sd-title">{name}</h2>
            <span className="sd-sym">{symbol}{quote?.sector ? ` · ${quote.sector}` : ''}</span>
          </div>
          <button className="sd-x" type="button" onClick={onClose} aria-label="Close stock details">✕</button>
        </div>

        <div className="sd-price">
          {quote ? (
            <>
              <span className="big num">{fmtInr(quote.price)}</span>
              <Delta value={quote.price - quote.prev_close} suffix="" />
              <Delta value={pct} />
            </>
          ) : q.error ? (
            <span className="note">Quote unavailable right now.</span>
          ) : (
            skel('36px', 220)
          )}
        </div>
        <div style={{ minHeight: 24 }}>
          {m && (
            <Provenance
              kind="data"
              source={m.source}
              delayMin={m.delay_min}
              asOf={`${new Intl.DateTimeFormat('en-IN', { timeZone: IST, day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false }).format(new Date(m.as_of))} IST`}
            />
          )}
        </div>

        <div className="sd-ranges" style={{ minHeight: 44 }}>
          {quote ? (
            <>
              <RangeBar title="Day range" low={quote.day_low} high={quote.day_high} value={quote.price} />
              <RangeBar title="52-week range" low={quote.year_low} high={quote.year_high} value={quote.price} />
            </>
          ) : (
            <>{skel('44px')}{skel('44px')}</>
          )}
        </div>

        <div className="sd-bar">
          <div className="seg" role="group" aria-label="Chart type">
            {(['area', 'candles'] as const).map((k) => (
              <button key={k} type="button" aria-pressed={mode === k} onClick={() => setMode(k)}>{k === 'area' ? 'Area' : 'Candles'}</button>
            ))}
          </div>
          <div className="seg" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button key={r} type="button" aria-pressed={range === r} onClick={() => (setRange(r), setTip(null))}>{r}</button>
            ))}
          </div>
        </div>
        <div className="sd-chart-wrap">
          {bars && bars.length > 0 ? (
            <PriceChart key={retry} bars={bars} mode={mode} intraday={intraday} onTip={onTip} />
          ) : ch.error || (bars && bars.length === 0) ? (
            <div className="sd-fail">
              <span>Chart unavailable right now</span>
              <button className="btn" type="button" onClick={() => setRetry((n) => n + 1)}>Retry</button>
            </div>
          ) : (
            skel('100%')
          )}
        </div>
        <div className="sd-tip">{tip ?? 'Move over or touch the chart to read a point.'}</div>
        <div style={{ minHeight: 24 }}>{ch.data?.meta && <Provenance kind="data" source={ch.data.meta.source} delayMin={ch.data.meta.delay_min} />}</div>
        {rows.length > 0 && (
          <details>
            <summary>View data as table</summary>
            <div className="sd-scroll">
              <table>
                <caption style={{ position: 'absolute', left: -9999 }}>Last {rows.length} bars, IST</caption>
                <thead><tr><th scope="col">Time</th><th scope="col">Open</th><th scope="col">High</th><th scope="col">Low</th><th scope="col">Close</th><th scope="col">Volume</th></tr></thead>
                <tbody>
                  {rows.map((b) => (
                    <tr key={b.t} className="num"><td>{rowFmt.format(new Date(b.t * 1000))}</td><td>{fmtNum(b.o)}</td><td>{fmtNum(b.h)}</td><td>{fmtNum(b.l)}</td><td>{fmtNum(b.c)}</td><td>{b.v.toLocaleString('en-IN')}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        )}

        {quote && (
          <dl className="sd-stats num">
            <div><dt>Market cap</dt><dd>{quote.market_cap ? fmtCr(quote.market_cap / 1e7) : '–'}</dd></div>
            <div><dt>P/E</dt><dd>{quote.pe ? fmtNum(quote.pe) : '–'}</dd></div>
            <div><dt>Day low</dt><dd>{fmtNum(quote.day_low)}</dd></div>
            <div><dt>Day high</dt><dd>{fmtNum(quote.day_high)}</dd></div>
            <div><dt>52w low</dt><dd>{fmtNum(quote.year_low)}</dd></div>
            <div><dt>52w high</dt><dd>{fmtNum(quote.year_high)}</dd></div>
            <div><dt>Volume</dt><dd>{quote.volume.toLocaleString('en-IN')}</dd></div>
            <div><dt>Sector</dt><dd>{quote.sector ?? '–'}</dd></div>
          </dl>
        )}

        <SipPanel id={`stock:${symbol}`} />

        <div className="sd-actions">
          <button className="btn primary" type="button" disabled={!quote} onClick={() => ask(`Why is ${name} ${dir} ${Math.abs(pct).toFixed(2)}% today?`)}>
            Ask ARIA: Why is {name} {dir} {Math.abs(pct).toFixed(2)}% today?
          </button>
          <button className="btn" type="button" onClick={() => ask(`Is ${name} fairly valued?`)}>Is {name} fairly valued?</button>
          <button className="btn" type="button" onClick={() => ask(`Compare ${name} with its peers`)}>Compare with peers</button>
          <button className="btn" type="button" aria-pressed={wl} onClick={() => toggleWatch(symbol)}>{wl ? '★ In your watchlist (remove)' : '☆ Add to watchlist'}</button>
        </div>

        <Intel symbol={symbol} onChat={() => ask(`Give me the full ARIA intelligence read on ${name}`)} />
      </div>
    </dialog>
  )
}

export function StockDrawer({ symbol, onClose, onAsk }: { symbol: string | null; onClose: () => void; onAsk: (q: string) => void }) {
  return symbol ? <Drawer key={symbol} symbol={symbol} onClose={onClose} onAsk={onAsk} /> : null
}
