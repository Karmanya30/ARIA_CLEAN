import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { IChartApi } from 'lightweight-charts'
import { api, type CompanyIntel } from '../../api'
import { useMarket } from '../../hooks/useMarket'
import { SipPanel } from '../explore/SipPanel'
import { Delta } from './Delta'
import { Provenance } from './Provenance'
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

/* ── helpers ──────────────────────────────────────────────────────────── */
const BAND_LABELS: Record<string, { label: string; emoji: string; color: string; desc: string; detail: string }> = {
  strong: {
    label: 'Strong conviction', emoji: '✅', color: 'var(--up)',
    desc: 'All key checks passed — fundamentals, valuation and market signals agree.',
    detail: 'ARIA found no major conflicts between the business quality, the price you pay and what the market is signalling. This alignment means the thesis rests on multiple, independent pillars — not just one good metric.'
  },
  mixed: {
    label: 'Mixed signals', emoji: '⚖️', color: '#d97706',
    desc: 'Some pillars look good, others raise concerns. Requires careful judgement.',
    detail: 'The evidence is split. Some aspects of the company are genuinely strong, but others are flagging caution. This does not mean avoid — it means understand which pillar you are betting on before deciding.'
  },
  weak: {
    label: 'Weak fundamentals', emoji: '⚠️', color: 'var(--down)',
    desc: 'Multiple warning signs detected. ARIA recommends caution.',
    detail: 'Two or more of the core pillars came back weak. That level of evidence against is hard to offset with a single positive. The risk of a fundamental disappointment is elevated here.'
  },
}

const PILLAR_DESC: Record<string, { short: string; what: string; how: string }> = {
  'Quality': {
    short: 'Is the business fundamentally good?',
    what: 'Measures how reliably the company earns money and converts those earnings into actual cash.',
    how: 'ARIA checks the Piotroski F-score (a 9-point checklist of earnings quality), cash conversion ratio (operating cash vs net profit), return on invested capital vs the cost of capital, and Buffett\'s consistency tests.'
  },
  'Valuation lenses': {
    short: 'Is the price you pay fair?',
    what: 'Asks whether the current stock price makes sense given what the business actually earns and owns.',
    how: 'ARIA applies four independent frameworks: Graham number (the highest a defensive investor should pay), Lynch\'s PEG ratio (price relative to growth), Greenblatt\'s earnings yield vs the risk-free rate, and a residual-income model (what the business is worth above its book value).'
  },
  'Growth': {
    short: 'Is the business growing fast enough?',
    what: 'Checks whether earnings and revenue are expanding at a pace that justifies the valuation.',
    how: 'Three-year CAGR for both EPS and revenue, and a cross-check that the management\'s forecast growth rate is actually funded by how much the business reinvests.'
  },
  'Financial safety': {
    short: 'Can the company handle a bad year?',
    what: 'Stress-tests the balance sheet — how much debt it carries and whether it has the cushion to service that debt if profits fall.',
    how: 'Altman Z-score (a multi-factor bankruptcy predictor), interest cover (profit vs interest owed), and debt-to-equity ratio, all compared against standard safe/unsafe thresholds.'
  },
  'Technical': {
    short: 'What is the market currently saying?',
    what: 'Reads the price action to see whether the market is rewarding or punishing this stock relative to the broader index.',
    how: '40-week moving average (uptrend or downtrend), 1-year return vs Nifty 50, weekly RSI (overbought / oversold), and position within the 52-week price range.'
  },
  'Sentiment': {
    short: 'What are the press and management signalling?',
    what: 'Analyses the emotional tone of recent news and the latest earnings call transcript.',
    how: 'A finance-trained language model scores each headline and management statement as positive, negative, or neutral. The net score is compared against a ±0.25 threshold to label the pillar.'
  },
}

const COMP_DESC: Record<string, string> = {
  'Quality':          'How well the business earns and retains money',
  'Financial safety': 'How resilient the balance sheet is',
  'Growth':           'How fast earnings and revenue are expanding',
  'Valuation lenses': 'How fairly the stock is priced vs what it earns',
  'Valuation upside': 'Gap between current price and ARIA\'s fair value estimate',
  'Technical':        'What the price trend and momentum suggest',
  'Tone':             'Overall tone from news headlines and management calls',
}

const DIV_WHAT: Record<string, string> = {
  tone_vs_cash: 'The headlines and management sound positive, but the business is not actually generating much cash — the optimism may not be grounded in real cash flows.',
  tone_vs_quality: 'The press/management tone is upbeat, but the underlying earnings quality is poor. Positive sentiment without fundamental backing is a common feature of stocks before a disappointment.',
  call_vs_news: 'Management\'s tone in the earnings call and what the press is reporting are pointing in opposite directions. One of them is likely to be proven wrong.',
  guidance_unfunded: 'Management is projecting strong growth, but the amount the company actually reinvests into the business cannot support that growth rate — the guidance may be optimistic.',
  value_trap: 'The valuation model shows a large margin of safety, but multiple business pillars are weak. Cheap stocks with deteriorating fundamentals are classic value traps.',
  price_vs_fundamentals_lag: 'The stock price has been drifting lower even though the underlying business is strong. This can be a temporary disconnect, or the market may know something the financials do not yet show.',
  price_vs_fundamentals_lead: 'The stock price is trending upward but the business quality is weak. Momentum is running ahead of what the fundamentals justify — a reversal risk.',
  contrarian: 'News and management tone are negative on a company with strong fundamentals and a safe balance sheet. This pattern sometimes precedes a re-rating when sentiment catches up.',
}

function ratingCls(r: string) {
  const l = r.toLowerCase()
  if (l === 'strong') return 'strong'
  if (l === 'weak')   return 'weak'
  if (l === 'n/a')    return 'mixed'
  return 'mixed'
}
function signCls(s: number) {
  if (s > 0) return 'pos'
  if (s < 0) return 'neg'
  return 'neu'
}
function signIcon(s: number) {
  if (s > 0) return '▲'
  if (s < 0) return '▼'
  return '–'
}
function dirCls(d: string) {
  const l = d.toLowerCase()
  if (l === 'bullish' || l === 'positive' || l === 'buy') return 'pos'
  if (l === 'bearish' || l === 'negative' || l === 'sell') return 'neg'
  return 'neu'
}
function netToLabel(n: number): { label: string; cls: string; desc: string } {
  if (n > 0.5)  return { label: 'Strongly bullish', cls: 'pos', desc: 'The overall tone is decisively positive.' }
  if (n > 0.25) return { label: 'Bullish', cls: 'pos', desc: 'More positive statements than negative.' }
  if (n < -0.5) return { label: 'Strongly bearish', cls: 'neg', desc: 'The overall tone is decisively negative.' }
  if (n < -0.25) return { label: 'Bearish', cls: 'neg', desc: 'More negative signals than positive.' }
  return { label: 'Neutral', cls: 'neu', desc: 'Positive and negative signals roughly cancel out.' }
}

/** Parse a reason text like "EPS 3-year CAGR 22.1%" into a friendlier explanation */
function humanReason(text: string, _sign: number): string {
  // Already long/readable — pass through
  if (text.length > 60) return text
  return text
}

function ScoreGauge({ score, band }: { score: number; band: string | null }) {
  const bandInfo = band ? BAND_LABELS[band] : null
  const color = band === 'strong' ? 'var(--up)' : band === 'weak' ? 'var(--down)' : '#d97706'
  const r = 44, cx = 56, cy = 56, stroke = 10
  const circ = 2 * Math.PI * r
  const arc = circ * 0.75  // 270° arc
  // starts at 225° (bottom-left), goes clockwise
  const startAngle = 225
  const endAngle = startAngle + 270 * (score / 100)
  const toRad = (d: number) => (d - 90) * Math.PI / 180
  const sx = cx + r * Math.cos(toRad(startAngle))
  const sy = cy + r * Math.sin(toRad(startAngle))
  const ex = cx + r * Math.cos(toRad(endAngle))
  const ey = cy + r * Math.sin(toRad(endAngle))
  const large = 270 * (score / 100) > 180 ? 1 : 0

  return (
    <div className="si-gauge-wrap">
      <svg width="112" height="112" viewBox="0 0 112 112" aria-label={`Score ${score} out of 100`}>
        {/* Track */}
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="var(--bg-inset)" strokeWidth={stroke}
          strokeDasharray={`${arc} ${circ}`} strokeDashoffset={0}
          strokeLinecap="round"
          transform={`rotate(135 ${cx} ${cy})`}
        />
        {/* Fill arc */}
        {score > 0 && (
          <path
            d={`M ${sx} ${sy} A ${r} ${r} 0 ${large} 1 ${ex} ${ey}`}
            fill="none" stroke={color} strokeWidth={stroke} strokeLinecap="round"
          />
        )}
        <text x={cx} y={cy - 6} textAnchor="middle" style={{ fontSize: 26, fontWeight: 800, fill: color }}>{Math.round(score)}</text>
        <text x={cx} y={cy + 11} textAnchor="middle" style={{ fontSize: 11, fill: 'var(--ink-muted)' }}>/ 100</text>
        {bandInfo && <text x={cx} y={cy + 25} textAnchor="middle" style={{ fontSize: 10, fill: color, fontWeight: 600 }}>{bandInfo.emoji} {band?.toUpperCase()}</text>}
      </svg>
    </div>
  )
}

function Intel({ symbol, onChat }: { symbol: string; onChat: () => void }) {
  const [st, setSt] = useState<{ s: 'idle' | 'load' | 'err'; d?: CompanyIntel }>({ s: 'idle' })
  const [openPillar, setOpenPillar] = useState<string | null>(null)
  const run = () => {
    setSt({ s: 'load' })
    api.companyIntel(symbol.replace(/\.(NS|BO)$/i, '')).then(
      (d) => setSt({ s: 'idle', d }),
      () => setSt({ s: 'err' }),
    )
  }

  const d = st.d
  const intel = d?.intelligence
  const sc = d?.scorecard
  const ratedComponents = (intel?.components ?? []).filter(c => c.value !== null)
  const bandInfo = intel?.band ? BAND_LABELS[intel.band] ?? null : null
  const ratedPillars = sc?.pillars.filter(p => p.rating !== 'n/a') ?? []

  return (
    <section className="mk-card" aria-live="polite" aria-busy={st.s === 'load'} style={{ display: 'grid', gap: 'var(--s-3)' }}>
      <div className="sd-h"><h3>ARIA Intelligence Report</h3><Provenance kind="ai" /></div>

      {intel ? (
        <div className="si-wrap">

          {/* ══ SECTION 1: Score hero ══ */}
          <div className="si-hero-card">
            <div className="si-hero-top">
              <ScoreGauge score={intel.score ?? 0} band={intel.band} />
              <div className="si-hero-text">
                {bandInfo && (
                  <>
                    <div className="si-band" style={{ color: bandInfo.color }}>{bandInfo.emoji} {bandInfo.label}</div>
                    <p className="si-verdict">{bandInfo.desc}</p>
                    <p className="si-verdict-detail">{bandInfo.detail}</p>
                  </>
                )}
                <div className="si-coverage-row">
                  <span className="si-coverage-label">Data coverage</span>
                  <div className="si-coverage-track">
                    <div className="si-coverage-fill" style={{ width: `${Math.round(intel.coverage * 100)}%` }} />
                  </div>
                  <span className="si-coverage-pct">{Math.round(intel.coverage * 100)}%</span>
                </div>
                {intel.low_evidence && (
                  <span className="si-low-ev">⚠ Low data coverage — treat this score as provisional</span>
                )}
              </div>
            </div>

            {/* Pillar summary chips */}
            {ratedPillars.length > 0 && (
              <div className="si-pillar-chips">
                {ratedPillars.map(p => (
                  <span key={p.name} className={`si-pillar-chip ${ratingCls(p.rating)}`}
                    title={`${p.name}: ${p.rating} (${p.points > 0 ? '+' : ''}${p.points} pts)`}>
                    {p.rating === 'strong' ? '✓' : p.rating === 'weak' ? '✗' : '~'} {p.name}
                  </span>
                ))}
              </div>
            )}

            <button className="btn si-chat-btn" type="button" onClick={onChat}>
              📋 Open full research report in ARIA chat ↗
            </button>
          </div>

          {/* ══ SECTION 2: ARIA's conclusion — plain English ══ */}
          {sc?.overlay?.reading && (
            <div className="si-section">
              <p className="si-sec-h">🔍 What ARIA concluded — and why</p>
              <div className="si-narrative">
                <div className="si-narrative-label">ARIA's overall read</div>
                <p className="si-narrative-text">{sc.overlay.reading}</p>
                {(sc.overlay.strong?.length > 0 || sc.overlay.weak?.length > 0) && (
                  <div className="si-narrative-pills">
                    {sc.overlay.strong?.map(s => (
                      <span key={s} className="si-narrative-pill strong">✓ {s} is strong</span>
                    ))}
                    {sc.overlay.weak?.map(w => (
                      <span key={w} className="si-narrative-pill weak">✗ {w} is weak</span>
                    ))}
                  </div>
                )}
              </div>
              {/* Score breakdown explanation */}
              <div className="si-score-context">
                <div className="si-score-context-row">
                  <span className="si-sck-label">Score range meaning</span>
                  <div className="si-score-bands">
                    <span className="si-score-band-item" style={{ color: 'var(--down)' }}>0–44 = Weak</span>
                    <span className="si-score-band-item" style={{ color: '#d97706' }}>45–69 = Mixed</span>
                    <span className="si-score-band-item" style={{ color: 'var(--up)' }}>70–100 = Strong</span>
                  </div>
                </div>
                <p className="si-score-context-note">
                  This score combines {ratedComponents.length} independently weighted signals — no single metric drives it. A high score means the majority of checks, from multiple disciplines, agree the stock looks sound. A low score means the opposite.
                </p>
              </div>
            </div>
          )}

          {/* ══ SECTION 3: Score components — what went in ══ */}
          {ratedComponents.length > 0 && (
            <div className="si-section">
              <p className="si-sec-h">📊 How the score was built — factor by factor</p>
              <p className="si-section-intro">Each bar below shows how strongly one factor scored (0 = worst possible, 100 = best possible). Factors are weighted differently: Quality matters more than Tone.</p>
              <div className="si-components">
                {ratedComponents.map((c) => {
                  const pct = Math.round((c.value ?? 0) * 100)
                  const isGood = pct >= 65
                  const isBad = pct <= 35
                  const fillColor = isGood ? 'var(--up)' : isBad ? 'var(--down)' : '#d97706'
                  const desc = COMP_DESC[c.name] ?? ''
                  return (
                    <div key={c.name} className="si-comp-row">
                      <div className="si-comp-header">
                        <span className="si-comp-label">{c.name}</span>
                        <span className="si-comp-meta">{c.weight}% weight</span>
                        <span className="si-comp-val" style={{ color: fillColor }}>{pct}/100</span>
                      </div>
                      {desc && <p className="si-comp-desc">{desc}</p>}
                      <div className="si-comp-track">
                        <div className="si-comp-fill" style={{ width: `${Math.max(2, pct)}%`, background: fillColor }} />
                      </div>
                      <p className="si-comp-reading">
                        {isGood ? `✓ Strong — scored ${pct}/100 on this factor` : isBad ? `✗ Weak — scored only ${pct}/100 on this factor` : `⚖ Mixed — scored ${pct}/100 on this factor`}
                      </p>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ══ SECTION 4: Scorecard pillars — evidence in full ══ */}
          {ratedPillars.length > 0 && (
            <div className="si-section">
              <p className="si-sec-h">📋 Detailed evidence — what we checked and what we found</p>
              <p className="si-section-intro">Click any pillar to see every individual data point that went into that rating. A ▲ means it helped the score; a ▼ means it hurt it.</p>
              <div className="si-pillars">
                {ratedPillars.map((p) => {
                  const pInfo = PILLAR_DESC[p.name]
                  const isOpen = openPillar === p.name
                  return (
                    <div key={p.name} className={`si-pillar ${isOpen ? 'open' : ''}`}>
                      <button
                        className="si-pillar-summary"
                        type="button"
                        aria-expanded={isOpen}
                        onClick={() => setOpenPillar(isOpen ? null : p.name)}
                      >
                        <div className="si-pillar-title-row">
                          <span className="si-pillar-name">{p.name}</span>
                          <span className={`si-rating ${ratingCls(p.rating)}`}>
                            {p.rating === 'strong' ? '✓ Strong' : p.rating === 'weak' ? '✗ Weak' : '⚖ Mixed'}
                          </span>
                          <span className="si-pillar-pts" style={{ color: p.points > 0 ? 'var(--up)' : p.points < 0 ? 'var(--down)' : 'var(--ink-muted)' }}>
                            {p.points > 0 ? `+${p.points}` : p.points} pts
                          </span>
                        </div>
                        {pInfo && <p className="si-pillar-short">{pInfo.short}</p>}
                        <svg className="si-pillar-chevron" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                          <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                        </svg>
                      </button>
                      {isOpen && (
                        <div className="si-pillar-body">
                          {pInfo && (
                            <div className="si-pillar-explain">
                              <div className="si-explain-row">
                                <span className="si-explain-head">What this pillar measures</span>
                                <p className="si-explain-text">{pInfo.what}</p>
                              </div>
                              <div className="si-explain-row">
                                <span className="si-explain-head">How ARIA calculated it</span>
                                <p className="si-explain-text">{pInfo.how}</p>
                              </div>
                            </div>
                          )}
                          <div className="si-reasons-list">
                            <p className="si-reasons-head">Individual data points ({p.reasons.length} checks):</p>
                            {p.reasons.length > 0
                              ? p.reasons.map((r, idx) => (
                                  <div key={idx} className={`si-reason ${signCls(r.sign)}`}>
                                    <span className={`si-reason-sign ${signCls(r.sign)}`}>{signIcon(r.sign)}</span>
                                    <div className="si-reason-body">
                                      <span className="si-reason-text">{humanReason(r.text, r.sign)}</span>
                                      {r.sign > 0 && <span className="si-reason-impact pos">Helped the score</span>}
                                      {r.sign < 0 && <span className="si-reason-impact neg">Hurt the score</span>}
                                      {r.sign === 0 && <span className="si-reason-impact neu">Neutral — no clear direction</span>}
                                    </div>
                                  </div>
                                ))
                              : <p className="note">No specific evidence recorded for this pillar.</p>
                            }
                          </div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ══ SECTION 5: Conflicting signals — the most important part ══ */}
          {intel.divergences.length > 0 && (
            <div className="si-section">
              <p className="si-sec-h">⚡ Where signals conflict — read this before deciding</p>
              <p className="si-section-intro">These are the places where different evidence sources disagree with each other. They do not mean the stock is bad — they mean the thesis has a tension point that needs to be resolved before acting.</p>
              <div className="si-divs">
                {intel.divergences.map((div) => {
                  const what = DIV_WHAT[div.id]
                  return (
                    <div key={div.id} className={`si-div sev-${div.severity.toLowerCase()}`}>
                      <div className="si-div-head">
                        <span className={`si-div-sev ${div.severity.toLowerCase()}`}>
                          {div.severity === 'HIGH' ? '🔴' : div.severity === 'MEDIUM' ? '🟡' : '🔵'} {div.severity} risk
                        </span>
                        <span className="si-div-title">{div.text}</span>
                      </div>
                      <div className="si-div-detail">
                        <p className="si-div-evidence"><strong>The data:</strong> {div.evidence}</p>
                        {what && <p className="si-div-what"><strong>What this means:</strong> {what}</p>}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* ══ SECTION 6: Earnings call sentiment ══ */}
          {d?.call?.available && d.call.period && (
            <div className="si-section">
              <p className="si-sec-h">📞 Management commentary — {d.call.period} earnings call</p>
              {d.call.net !== undefined && d.call.net !== null && (() => {
                const nl = netToLabel(d.call.net)
                return (
                  <div className="si-call-tone-card">
                    <div className="si-call-tone-row">
                      <span className="si-call-tone-label">Management tone</span>
                      <span className={`si-news-dir ${nl.cls}`}>{nl.label}</span>
                      <span className="si-call-net-num">net score: {d.call.net > 0 ? '+' : ''}{d.call.net.toFixed(2)}</span>
                    </div>
                    <div className="si-sentiment-bar-wrap">
                      <div className="si-sentiment-bar-track">
                        <div className="si-sentiment-bar-fill"
                          style={{
                            width: `${Math.abs(d.call.net) * 100}%`,
                            left: d.call.net >= 0 ? '50%' : `${50 - Math.abs(d.call.net) * 50}%`,
                            background: d.call.net > 0.25 ? 'var(--up)' : d.call.net < -0.25 ? 'var(--down)' : '#d97706'
                          }}
                        />
                        <div className="si-sentiment-bar-mid" />
                      </div>
                      <div className="si-sentiment-bar-labels">
                        <span>Bearish</span><span>Neutral</span><span>Bullish</span>
                      </div>
                    </div>
                    <p className="si-call-tone-desc">{nl.desc} A score of ±0.25 or more is considered a clear directional signal.</p>
                  </div>
                )
              })()}
              {d.call.themes && Object.keys(d.call.themes).length > 0 && (
                <div className="si-themes">
                  <p className="si-reasons-head">Key topics discussed:</p>
                  {Object.entries(d.call.themes).flatMap(([theme, items]) =>
                    items.map((item, idx) => (
                      <div key={`${theme}-${idx}`} className="si-theme-row">
                        <span className="si-theme-cat">{theme}</span>
                        {item.label && (
                          <span className={`si-theme-label-chip ${item.label.toLowerCase()}`}>{item.label}</span>
                        )}
                        <span className="si-theme-text">{item.text}</span>
                      </div>
                    ))
                  )}
                </div>
              )}
            </div>
          )}

          {/* ══ SECTION 7: News that shaped the score ══ */}
          {d?.news && d.news.length > 0 && (
            <div className="si-section">
              <p className="si-sec-h">📰 News that shaped this score</p>
              <p className="si-section-intro">These {Math.min(d.news.length, 6)} headlines were scored by FinBERT (a finance-trained AI model) and fed into the Sentiment and Tone components of the intelligence score.</p>
              <div className="si-news">
                {d.news.slice(0, 6).map((n, idx) => (
                  <div key={idx} className="si-news-row">
                    <div className="si-news-top">
                      <span className={`si-news-dir ${dirCls(n.direction ?? '')}`}>{n.direction ?? 'Not scored'}</span>
                      {typeof n.net === 'number' && (
                        <span className="si-news-net" style={{ color: n.net > 0.1 ? 'var(--up)' : n.net < -0.1 ? 'var(--down)' : 'var(--ink-muted)' }}>
                          {n.net > 0 ? '+' : ''}{n.net.toFixed(2)}
                        </span>
                      )}
                      <span className="si-news-source">{n.source}</span>
                    </div>
                    <span className="si-news-title">{n.title}</span>
                    <span className="si-news-impact">
                      {(n.direction ?? '').toLowerCase().includes('bull') || (n.direction ?? '').toLowerCase().includes('pos')
                        ? 'This headline was flagged as positive — it contributed to a higher Tone score.'
                        : (n.direction ?? '').toLowerCase().includes('bear') || (n.direction ?? '').toLowerCase().includes('neg')
                        ? 'This headline was flagged as negative — it pulled down the Tone score.'
                        : 'This headline was neutral — it did not materially affect the Tone score.'
                      }
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

        </div>
      ) : (
        <div className="si-idle">
          <div className="si-idle-icon">🔬</div>
          <p className="si-idle-title">Get ARIA's full intelligence read on this company</p>
          <p className="note">
            ARIA will analyse this company across 7 independent lenses — earnings quality, valuation frameworks (Graham, Lynch, Greenblatt), growth, financial safety, technical momentum, and sentiment from news and the latest earnings call. Takes about 15 seconds.
          </p>
          <div className="si-idle-checks">
            {['Business quality (Piotroski, Buffett tests)', 'Valuation (Graham number, PEG, EVA)', 'Growth sustainability', 'Financial safety (Altman Z, debt cover)', 'Technical momentum & trend', 'News & earnings call sentiment'].map(c => (
              <span key={c} className="si-idle-check">✓ {c}</span>
            ))}
          </div>
          <button className="btn primary" type="button" onClick={run} disabled={st.s === 'load'}>
            {st.s === 'load' ? '⏳ Analysing, about 15 seconds…' : st.s === 'err' ? '⚠ Could not score. Try again' : '🔬 Run ARIA intelligence score'}
          </button>
        </div>
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
