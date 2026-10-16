import { useState } from 'react'
import { api } from '../../api'
import type { CompanyIntel, SentimentResult } from '../../api'
import { ForYou } from '../chat/IntelligenceSummary'
import './ResearchTab.css'
import './IntelligenceTab.css'

/* ── helpers ─────────────────────────────────────────────────────────── */
const EXAMPLES = ['TCS', 'Infosys', 'HDFC Bank', 'Reliance', 'ITC', 'Larsen & Toubro']
const SAMPLE_TEXT = 'Order inflow beat expectations and margins widened\nThe company cut its guidance on weak demand\nBoard approves routine AGM notice'
const STEPS = ['Fetching financial statements…', 'Reading recent news…', 'Reading the latest earnings call…', 'Scoring the evidence…']

const BAND: Record<string, { label: string; emoji: string; color: string; desc: string; detail: string }> = {
  strong: {
    label: 'Strong conviction', emoji: '✅', color: 'var(--green)',
    desc: 'All key checks passed — fundamentals, valuation and market signals agree.',
    detail: 'ARIA found no major conflicts between the business quality, the price you pay and what the market is signalling. This alignment means the thesis rests on multiple, independent pillars — not just one good metric.',
  },
  mixed: {
    label: 'Mixed signals', emoji: '⚖️', color: 'var(--amber)',
    desc: 'Some pillars look good, others raise concerns. Requires careful judgement.',
    detail: 'The evidence is split. Some aspects of the company are genuinely strong, but others are flagging caution. This does not mean avoid — it means understand which pillar you are betting on before deciding.',
  },
  weak: {
    label: 'Weak fundamentals', emoji: '⚠️', color: 'var(--red)',
    desc: 'Multiple warning signs detected. ARIA recommends caution.',
    detail: 'Two or more of the core pillars came back weak. That level of evidence against is hard to offset with a single positive. The risk of a fundamental disappointment is elevated here.',
  },
}

const PILLAR_INFO: Record<string, { short: string; what: string; how: string }> = {
  'Quality': {
    short: 'Is the business fundamentally good?',
    what: 'Measures how reliably the company earns money and converts those earnings into actual cash.',
    how: 'ARIA checks the Piotroski F-score (a 9-point checklist of earnings quality), cash conversion ratio (operating cash vs net profit), return on invested capital vs the cost of capital, and Buffett\'s consistency tests.',
  },
  'Valuation lenses': {
    short: 'Is the price you pay fair?',
    what: 'Asks whether the current stock price makes sense given what the business actually earns and owns.',
    how: 'ARIA applies four independent frameworks: Graham number (the highest a defensive investor should pay), Lynch\'s PEG ratio (price relative to growth), Greenblatt\'s earnings yield vs the risk-free rate, and a residual-income model.',
  },
  'Growth': {
    short: 'Is the business growing fast enough?',
    what: 'Checks whether earnings and revenue are expanding at a pace that justifies the valuation.',
    how: 'Three-year CAGR for both EPS and revenue, and a cross-check that the management\'s forecast growth rate is actually funded by how much the business reinvests.',
  },
  'Financial safety': {
    short: 'Can the company handle a bad year?',
    what: 'Stress-tests the balance sheet — how much debt it carries and whether it has the cushion to service that debt if profits fall.',
    how: 'Altman Z-score (a multi-factor bankruptcy predictor), interest cover (profit vs interest owed), and debt-to-equity ratio, all compared against standard safe/unsafe thresholds.',
  },
  'Technical': {
    short: 'What is the market currently saying?',
    what: 'Reads the price action to see whether the market is rewarding or punishing this stock relative to the broader index.',
    how: '40-week moving average (uptrend or downtrend), 1-year return vs Nifty 50, weekly RSI (overbought / oversold), and position within the 52-week price range.',
  },
  'Sentiment': {
    short: 'What are the press and management signalling?',
    what: 'Analyses the emotional tone of recent news and the latest earnings call transcript.',
    how: 'FinBERT (a finance-trained language model) scores each headline and management statement. The net score is compared against a ±0.25 threshold to label the pillar.',
  },
}

const COMP_DESC: Record<string, string> = {
  'Quality': 'How well the business earns and retains money',
  'Financial safety': 'How resilient the balance sheet is',
  'Growth': 'How fast earnings and revenue are expanding',
  'Valuation lenses': 'How fairly the stock is priced vs what it earns',
  'Valuation upside': 'Gap between current price and ARIA\'s fair value estimate',
  'Technical': 'What the price trend and momentum suggest',
  'Tone': 'Overall tone from news headlines and management calls',
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

const scoreColor = (s: number) => s >= 70 ? 'var(--green)' : s >= 45 ? 'var(--amber)' : 'var(--red)'
const signCls = (s: number) => s > 0 ? 'up' : s < 0 ? 'down' : 'flat'
const signIcon = (s: number) => s > 0 ? '▲' : s < 0 ? '▼' : '–'
const dirCls = (d: string | null) => {
  const l = (d ?? '').toLowerCase()
  if (l.includes('bull') || l.includes('pos')) return 'up'
  if (l.includes('bear') || l.includes('neg')) return 'down'
  return 'flat'
}
const netToLabel = (n: number) => {
  if (n > 0.5)  return { label: 'Strongly bullish', cls: 'up',   desc: 'The overall tone is decisively positive.' }
  if (n > 0.25) return { label: 'Bullish',          cls: 'up',   desc: 'More positive statements than negative.' }
  if (n < -0.5) return { label: 'Strongly bearish', cls: 'down', desc: 'The overall tone is decisively negative.' }
  if (n < -0.25) return { label: 'Bearish',         cls: 'down', desc: 'More negative signals than positive.' }
  return            { label: 'Neutral',              cls: 'flat', desc: 'Positive and negative signals roughly cancel out.' }
}
const num = (n: number | null | undefined) => n == null || !Number.isFinite(n) ? 'unavailable' : (n > 0 ? '+' : '') + n.toFixed(2)

function friendly(e: unknown): string {
  const m = e instanceof Error ? e.message : ''
  return /404|not found/i.test(m)
    ? 'We could not find that company. Try its full name or NSE symbol, e.g. "Infosys" or "INFY".'
    : 'Something went wrong while analysing. Please try again in a moment.'
}

/** Standalone company-intelligence score + free-text sentiment, straight from the backend. */
export function IntelligenceTab() {
  const [q, setQ] = useState('')
  const [data, setData] = useState<CompanyIntel | null>(null)
  const [busy, setBusy] = useState(false)
  const [step, setStep] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [sent, setSent] = useState<SentimentResult | null>(null)
  const [sBusy, setSBusy] = useState(false)
  const [sError, setSError] = useState<string | null>(null)
  const [openPillar, setOpenPillar] = useState<string | null>(null)

  async function analyse(name: string) {
    const query = name.trim()
    if (!query || busy) return
    setQ(query)
    setBusy(true)
    setError(null)
    setStep(0)
    setOpenPillar(null)
    const timer = window.setInterval(() => setStep((s) => Math.min(s + 1, STEPS.length - 1)), 4000)
    try {
      setData(await api.companyIntel(query))
    } catch (e) {
      setData(null)
      setError(friendly(e))
    } finally {
      window.clearInterval(timer)
      setBusy(false)
    }
  }

  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)

  async function score() {
    setSBusy(true)
    setSError(null)
    try {
      setSent(await api.sentiment(lines.slice(0, 50)))
    } catch {
      setSError('Could not score the text. Please try again.')
    } finally {
      setSBusy(false)
    }
  }

  const intel = data?.intelligence
  const sc    = data?.scorecard
  const ratedPillars     = sc?.pillars.filter(p => p.rating !== 'n/a') ?? []
  const ratedComponents  = (intel?.components ?? []).filter(c => c.value !== null)
  const bandInfo = intel?.band ? BAND[intel.band] ?? null : null

  return (
    <div className="ri">
      <header>
        <h1>Company Intelligence</h1>
        <p className="ri-lead">
          One score that weighs business quality, valuation, price trend and what the news and management are saying —
          and flags where they disagree. A way to decide where to look closer, not a recommendation.
        </p>
      </header>

      <section aria-label="Analyse a company">
        <form className="ri-form" onSubmit={(e) => { e.preventDefault(); void analyse(q) }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company name or symbol, e.g. Infosys" aria-label="Company" autoComplete="off" />
          <button type="submit" className="ri-primary" disabled={busy || !q.trim()}>{busy ? 'Analysing…' : 'Analyse'}</button>
        </form>
        {!data && !busy && (
          <div className="ri-chips" aria-label="Examples">
            <span>Try</span>
            {EXAMPLES.map((x) => <button key={x} type="button" className="ri-chip" onClick={() => void analyse(x)}>{x}</button>)}
          </div>
        )}
        {busy && (
          <div className="ri-progress" role="status" aria-live="polite">
            <span className="ri-spin" aria-hidden="true" />
            <div>
              <strong>{STEPS[step]}</strong>
              <div className="ri-sub">The first look at a company can take up to 30 seconds; repeat visits are instant.</div>
            </div>
          </div>
        )}
        {error && <p className="ri-error" role="alert">{error}</p>}

        {data && intel && !busy && (
          <div className="ri-result">
            <button type="button" className="ri-back" onClick={() => { setData(null); setQ('') }}>← New search</button>

            {/* ══ SECTION 1: Score hero ══ */}
            <div className="ri-hero">
              <div className="ri-ring" style={{ ['--p' as string]: intel.score, ['--c' as string]: scoreColor(intel.score ?? 0) }}
                role="img" aria-label={`Score ${Math.round(intel.score ?? 0)} out of 100`}>
                <span>{Math.round(intel.score ?? 0)}</span><small>/ 100</small>
              </div>
              <div className="ri-hero-text">
                <div className="ri-name">{data.company.name} <span>{data.company.symbol}</span></div>
                {bandInfo && (
                  <>
                    <div className="ri-band" style={{ color: bandInfo.color }}>{bandInfo.emoji} {bandInfo.label}</div>
                    <p className="ri-hero-desc">{bandInfo.desc}</p>
                    <p className="ri-hero-detail">{bandInfo.detail}</p>
                  </>
                )}
                <div className="ri-coverage-row">
                  <span className="ri-coverage-label">Data coverage</span>
                  <div className="ri-coverage-track">
                    <div className="ri-coverage-fill" style={{ width: `${Math.round(intel.coverage * 100)}%` }} />
                  </div>
                  <span className="ri-coverage-pct">{Math.round(intel.coverage * 100)}%</span>
                </div>
                {intel.low_evidence && (
                  <p className="ri-warn">⚠ Only {Math.round(intel.coverage * 100)}% of signals were available — treat this score as provisional.</p>
                )}
              </div>
            </div>

            {/* Pillar chips summary */}
            {ratedPillars.length > 0 && (
              <div className="ri-chips ri-pillar-chips">
                {ratedPillars.map(p => (
                  <span key={p.name}
                    className={`ri-pillar-chip ${p.rating === 'strong' ? 'up' : p.rating === 'weak' ? 'down' : 'flat'}`}
                    title={`${p.name}: ${p.rating} (${p.points > 0 ? '+' : ''}${p.points} pts)`}>
                    {p.rating === 'strong' ? '✓' : p.rating === 'weak' ? '✗' : '~'} {p.name}
                  </span>
                ))}
              </div>
            )}

            <ForYou data={data.for_you} />

            {/* ══ SECTION 2: ARIA's conclusion ══ */}
            {sc?.overlay?.reading && (
              <div className="ri-section">
                <h2>🔍 What ARIA concluded — and why</h2>
                <div className="ri-narrative">
                  <div className="ri-narrative-label">ARIA's overall read</div>
                  <p className="ri-narrative-text">{sc.overlay.reading}</p>
                  {(sc.overlay.strong?.length > 0 || sc.overlay.weak?.length > 0) && (
                    <div className="ri-narrative-pills">
                      {sc.overlay.strong?.map(s => <span key={s} className="ri-npill up">✓ {s} is strong</span>)}
                      {sc.overlay.weak?.map(w => <span key={w} className="ri-npill down">✗ {w} is weak</span>)}
                    </div>
                  )}
                </div>
                <div className="ri-score-context">
                  <div className="ri-score-bands-row">
                    <span className="ri-score-bands-label">Score range:</span>
                    <span style={{ color: 'var(--red)', fontWeight: 700 }}>0–44 = Weak</span>
                    <span style={{ color: 'var(--amber)', fontWeight: 700 }}>45–69 = Mixed</span>
                    <span style={{ color: 'var(--green)', fontWeight: 700 }}>70–100 = Strong</span>
                  </div>
                  <p className="ri-sub">
                    This score combines {ratedComponents.length} independently weighted signals. No single metric drives it — a high score means the majority of checks, from multiple disciplines, agree the stock looks sound.
                  </p>
                </div>
              </div>
            )}

            {/* ══ SECTION 3: Score components ══ */}
            {ratedComponents.length > 0 && (
              <div className="ri-section">
                <h2>📊 How the score was built — factor by factor</h2>
                <p className="ri-sub">Each bar shows how strongly one factor scored (0 = weakest, 100 = strongest). Factors carry different weights.</p>
                <div className="ri-bars">
                  {ratedComponents.map((c) => {
                    const pct = Math.round((c.value ?? 0) * 100)
                    const col = scoreColor(pct)
                    const desc = COMP_DESC[c.name] ?? ''
                    return (
                      <div key={c.name} className="ri-bar-v2">
                        <div className="ri-bar-header">
                          <div className="ri-bar-left">
                            <span className="ri-bar-name">{c.name}</span>
                            {desc && <span className="ri-bar-desc">{desc}</span>}
                          </div>
                          <div className="ri-bar-right">
                            <span className="ri-bar-weight">{c.weight}% weight</span>
                            <b style={{ color: col }}>{pct}/100</b>
                          </div>
                        </div>
                        <div className="ri-track">
                          <div style={{ width: `${Math.max(2, pct)}%`, background: col, height: '100%', borderRadius: 'inherit' }} />
                        </div>
                        <span className="ri-bar-reading" style={{ color: col }}>
                          {pct >= 65 ? `✓ Strong — scored ${pct}/100` : pct <= 35 ? `✗ Weak — scored only ${pct}/100` : `⚖ Mixed — scored ${pct}/100`}
                        </span>
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* ══ SECTION 4: Conflicting signals ══ */}
            {intel.divergences.length > 0 && (
              <div className="ri-section">
                <h2>⚡ Where signals conflict — read this before deciding</h2>
                <p className="ri-sub">These are the places where different evidence sources disagree with each other. They do not mean the stock is bad — they mean the thesis has a tension point to resolve before acting.</p>
                {intel.divergences.map((d) => {
                  const what = DIV_WHAT[d.id]
                  return (
                    <div key={d.id} className={`ri-flag ri-flag-${d.severity.toLowerCase()}`}>
                      <div className="ri-flag-head">
                        <span className={`ri-flag-sev ${d.severity.toLowerCase()}`}>
                          {d.severity === 'HIGH' ? '🔴' : d.severity === 'MEDIUM' ? '🟡' : '🔵'} {d.severity} risk
                        </span>
                        <strong>{d.text}</strong>
                      </div>
                      <p className="ri-sub"><strong>The data:</strong> {d.evidence}</p>
                      {what && <p className="ri-flag-what"><strong>What this means:</strong> {what}</p>}
                    </div>
                  )
                })}
              </div>
            )}

            {/* ══ SECTION 5: Detailed evidence — pillars ══ */}
            {ratedPillars.length > 0 && (
              <div className="ri-section">
                <h2>📋 Detailed evidence — what we checked and what we found</h2>
                <p className="ri-sub">Click any pillar to expand the full evidence. A ▲ means it helped the score; a ▼ means it hurt it.</p>
                <div className="ri-pillars">
                  {ratedPillars.map((p) => {
                    const pInfo = PILLAR_INFO[p.name]
                    const isOpen = openPillar === p.name
                    return (
                      <div key={p.name} className={`ri-pillar ${isOpen ? 'open' : ''}`}>
                        <button
                          className="ri-pillar-btn"
                          type="button"
                          aria-expanded={isOpen}
                          onClick={() => setOpenPillar(isOpen ? null : p.name)}
                        >
                          <div className="ri-pillar-title">
                            <span className="ri-pillar-name">{p.name}</span>
                            <span className={`ri-pill2 ${p.rating === 'strong' ? 'up' : p.rating === 'weak' ? 'down' : 'flat'}`}>
                              {p.rating === 'strong' ? '✓ Strong' : p.rating === 'weak' ? '✗ Weak' : '⚖ Mixed'}
                            </span>
                            <span className={`ri-pillar-pts ${signCls(p.points)}`}>
                              {p.points > 0 ? `+${p.points}` : p.points} pts
                            </span>
                          </div>
                          {pInfo && <p className="ri-pillar-short">{pInfo.short}</p>}
                          <svg className="ri-pillar-chevron" width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
                            <path d="M5 3l4 4-4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                          </svg>
                        </button>
                        {isOpen && (
                          <div className="ri-pillar-body">
                            {pInfo && (
                              <div className="ri-pillar-explain">
                                <div>
                                  <div className="ri-explain-head">What this pillar measures</div>
                                  <p className="ri-sub">{pInfo.what}</p>
                                </div>
                                <div>
                                  <div className="ri-explain-head">How ARIA calculated it</div>
                                  <p className="ri-sub">{pInfo.how}</p>
                                </div>
                              </div>
                            )}
                            <div className="ri-explain-head" style={{ marginBottom: 6 }}>Individual data points ({p.reasons.length} checks):</div>
                            {p.reasons.length > 0
                              ? p.reasons.map((r, idx) => (
                                  <div key={idx} className={`ri-reason ri-reason-v2 ${signCls(r.sign)}`}>
                                    <span className={`ri-mark ${signCls(r.sign)}`} aria-hidden="true">{signIcon(r.sign)}</span>
                                    <div>
                                      <span>{r.text}</span>
                                      <span className={`ri-impact ${signCls(r.sign)}`}>
                                        {r.sign > 0 ? ' — helped the score' : r.sign < 0 ? ' — hurt the score' : ' — neutral'}
                                      </span>
                                    </div>
                                  </div>
                                ))
                              : <p className="ri-sub">No specific evidence recorded for this pillar.</p>
                            }
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* ══ SECTION 6: News headlines ══ */}
            {data.news.length > 0 && (
              <div className="ri-section">
                <h2>📰 News that shaped this score</h2>
                <p className="ri-sub">
                  These {Math.min(data.news.length, 6)} headlines were scored by FinBERT (a finance-trained AI model) and fed into the Sentiment and Tone components.
                </p>
                {data.news.slice(0, 6).map((n, k) => (
                  <div key={k} className="ri-news-v2">
                    <div className="ri-news-top">
                      <span className={`ri-pill ri-pill-${dirCls(n.direction)}`}>{n.direction} {num(n.net)}</span>
                      <span className="ri-sub" style={{ marginLeft: 'auto' }}>{n.source} · {n.date}</span>
                    </div>
                    <div className="ri-news-title">{n.title}</div>
                    <div className="ri-sub ri-news-impact">
                      {dirCls(n.direction) === 'up'
                        ? 'Flagged as positive — contributed to a higher Tone score.'
                        : dirCls(n.direction) === 'down'
                        ? 'Flagged as negative — pulled down the Tone score.'
                        : 'Neutral — did not materially affect the Tone score.'}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* ══ SECTION 7: Earnings call ══ */}
            <div className="ri-section">
              <h2>📞 Management commentary — latest earnings call</h2>
              {data.call.available ? (
                <>
                  {data.call.net !== undefined && data.call.net !== null && (() => {
                    const nl = netToLabel(data.call.net)
                    return (
                      <div className="ri-call-tone">
                        <div className="ri-call-tone-row">
                          <span className="ri-sub">Management tone</span>
                          <span className={`ri-pill ri-pill-${nl.cls}`}>{nl.label}</span>
                          <span className="ri-sub">net score: {num(data.call.net)}</span>
                        </div>
                        <div className="ri-sentiment-track">
                          <div className="ri-sentiment-fill" style={{
                            width: `${Math.abs(data.call.net) * 50}%`,
                            left: data.call.net >= 0 ? '50%' : `${50 - Math.abs(data.call.net) * 50}%`,
                            background: data.call.net > 0.25 ? 'var(--green)' : data.call.net < -0.25 ? 'var(--red)' : 'var(--amber)'
                          }} />
                          <div className="ri-sentiment-mid" />
                        </div>
                        <div className="ri-sentiment-labels"><span>Bearish</span><span>Neutral</span><span>Bullish</span></div>
                        <p className="ri-sub">{nl.desc} A score of ±0.25 or more is a clear directional signal. Period: {data.call.period}</p>
                      </div>
                    )
                  })()}
                  {data.call.themes && Object.keys(data.call.themes).length > 0 && (
                    <>
                      <p className="ri-sub" style={{ marginTop: 8 }}>Key topics discussed:</p>
                      {Object.entries(data.call.themes).flatMap(([theme, qs]) =>
                        qs.map((item, idx) => (
                          <div key={`${theme}-${idx}`} className="ri-quote">
                            <small>
                              {theme}
                              {item.label && <span className={`ri-pill ri-pill-${item.label.toLowerCase() === 'buy' ? 'up' : item.label.toLowerCase() === 'sell' ? 'down' : 'flat'}`} style={{ marginLeft: 8, fontSize: 10 }}>{item.label}</span>}
                            </small>
                            "{item.text}"
                          </div>
                        ))
                      )}
                    </>
                  )}
                </>
              ) : <p className="ri-sub">No earnings-call transcript was available for this company.</p>}
            </div>

          </div>
        )}
      </section>

      <details className="ri-tool" open={!!sent}>
        <summary>▶ Check the tone of any text</summary>
        <p className="ri-sub">Paste headlines or sentences, one per line (up to 50). Each is scored positive, neutral or negative by FinBERT.</p>
        <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="One text per line" aria-label="Texts to score" />
        <div className="ri-actions">
          <button type="button" className="ri-primary" disabled={sBusy || !lines.length} onClick={() => void score()}>{sBusy ? 'Scoring…' : 'Score text'}</button>
          {!text && <button type="button" className="ri-chip" onClick={() => setText(SAMPLE_TEXT)}>Use an example</button>}
          {lines.length > 50 && <span className="ri-sub">Only the first 50 lines are scored.</span>}
        </div>
        {sError && <p className="ri-error" role="alert">{sError}</p>}
        {sent && (
          <>
            <p className="ri-sub">
              Overall <strong>{sent.label}</strong> ({num(sent.net)}) ·{' '}
              {sent.engine === 'finbert' ? 'scored by FinBERT, a model trained on financial text' : 'quick keyword read (the language model is still loading)'}
            </p>
            {sent.items.map((it, k) => (
              <div key={k} className="ri-news-v2">
                <span className={`ri-pill ri-pill-${it.label === 'positive' ? 'up' : it.label === 'negative' ? 'down' : 'flat'}`}>
                  {it.label} {num(it.net)}
                </span>
                <div>{it.text}</div>
              </div>
            ))}
          </>
        )}
      </details>
    </div>
  )
}
