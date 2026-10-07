import { useState } from 'react'
import { api } from '../../api'
import type { CompanyIntel, SentimentResult } from '../../api'
import { ForYou } from '../chat/IntelligenceSummary'
import './ResearchTab.css'
import './IntelligenceTab.css'

const TONE: Record<string, string> = {
  strong: 'var(--green)', mixed: 'var(--amber)', weak: 'var(--red)',
  positive: 'var(--green)', neutral: 'var(--amber)', negative: 'var(--red)',
  high: 'var(--red)', medium: 'var(--amber)', low: 'var(--ink-faint)',
}
const colour = (k: string | null | undefined) => TONE[(k ?? '').toLowerCase()] ?? 'var(--ink-faint)'
const scoreColour = (s: number) => (s >= 70 ? 'var(--green)' : s >= 45 ? 'var(--amber)' : 'var(--red)')
const num = (n: number) => (n > 0 ? '+' : '') + n.toFixed(2)
const mark = (s: string | number) => (Number(s) > 0 ? '▲' : Number(s) < 0 ? '▼' : '●')
const markClass = (s: string | number) => (Number(s) > 0 ? 'up' : Number(s) < 0 ? 'down' : 'flat')
const EXAMPLES = ['TCS', 'Infosys', 'HDFC Bank', 'Reliance', 'ITC', 'Larsen & Toubro']
const SAMPLE_TEXT = 'Order inflow beat expectations and margins widened\nThe company cut its guidance on weak demand\nBoard approves routine AGM notice'
const STEPS = ['Fetching financial statements…', 'Reading recent news…', 'Reading the latest earnings call…', 'Scoring the evidence…']

function friendly(e: unknown): string {
  const m = e instanceof Error ? e.message : ''
  return /404|not found/i.test(m)
    ? 'We could not find that company. Try its full name or NSE symbol, e.g. “Infosys” or “INFY”.'
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

  async function analyse(name: string) {
    const query = name.trim()
    if (!query || busy) return
    setQ(query)
    setBusy(true)
    setError(null)
    setStep(0)
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

  const i = data?.intelligence
  const quotes = Object.entries(data?.call.themes ?? {})

  return (
    <div className="ri">
      <header>
        <h1>Company intelligence</h1>
        <p className="ri-lead">
          One score that weighs business quality, valuation, price trend and what the news and management are saying, and flags
          where they disagree. It is a way to decide where to look closer, not a recommendation.
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

        {data && i && !busy && (
          <div className="ri-result">
            <button type="button" className="ri-back" onClick={() => { setData(null); setQ('') }}>← New search</button>
            <div className="ri-hero">
              <div className="ri-ring" style={{ ['--p' as string]: i.score, ['--c' as string]: scoreColour(i.score) }} role="img" aria-label={`Score ${Math.round(i.score)} out of 100`}>
                <span>{Math.round(i.score)}</span><small>/100</small>
              </div>
              <div className="ri-hero-text">
                <div className="ri-name">{data.company.name} <span>{data.company.symbol}</span></div>
                <div className="ri-band" style={{ color: scoreColour(i.score) }}>{i.band === 'strong' ? 'Strong' : i.band === 'weak' ? 'Weak' : 'Mixed'} overall</div>
                <p>{data.response}</p>
                {i.low_evidence && <p className="ri-warn">Only {Math.round(i.coverage * 100)}% of the evidence was available for this company, so treat the score with caution.</p>}
              </div>
            </div>
            <ForYou data={data.for_you} />

            {i.divergences.length > 0 && (
              <>
                <h2>Where the signals disagree</h2>
                {i.divergences.map((d) => (
                  <div key={d.id} className="ri-flag" style={{ borderLeftColor: colour(d.severity) }}>
                    <div><strong>{d.text}</strong> <span className="ri-tag" style={{ color: colour(d.severity) }}>{d.severity} priority</span></div>
                    <div className="ri-sub">{d.evidence}</div>
                  </div>
                ))}
              </>
            )}
            {data.scorecard.overlay?.reading && <p className="ri-read">{data.scorecard.overlay.reading}</p>}

            <h2>What drives the score</h2>
            <div className="ri-bars">
              {i.components.map((c) => (
                <div key={c.name} className="ri-bar">
                  <span>{c.name} <small>weight {c.weight}%</small></span>
                  <div className="ri-track"><div style={{ width: `${Math.round(c.value * 100)}%`, background: scoreColour(c.value * 100) }} /></div>
                  <b>{Math.round(c.value * 100)}</b>
                </div>
              ))}
            </div>

            <h2>The six pillars</h2>
            <div className="ri-grid">
              {data.scorecard.pillars.map((p) => (
                <div key={p.name} className="ri-card">
                  <div className="ri-card-head">
                    <strong>{p.name}</strong>
                    <span className="ri-pill" style={{ background: colour(p.rating) }}>{p.rating === 'n/a' ? 'no data' : p.rating}</span>
                  </div>
                  {p.reasons.length === 0 && <div className="ri-sub">Nothing to measure for this company.</div>}
                  {p.reasons.map((r, n) => (
                    <div key={n} className="ri-reason"><span className={`ri-mark ${markClass(r.sign)}`} aria-hidden="true">{mark(r.sign)}</span>{r.text}</div>
                  ))}
                </div>
              ))}
            </div>

            {data.news.length > 0 && <h2>Recent headlines</h2>}
            {data.news.slice(0, 6).map((n, k) => (
              <div key={k} className="ri-news">
                <span className="ri-pill" style={{ background: colour(n.direction) }}>{n.direction} {num(n.net)}</span>
                <div>{n.title}<div className="ri-sub">{n.source} · {n.date}</div></div>
              </div>
            ))}

            <h2>Management on the latest earnings call</h2>
            {data.call.available ? (
              <>
                <p className="ri-sub">{data.call.period} · overall tone {num(data.call.net ?? 0)} (−1 very negative, +1 very positive)</p>
                {quotes.slice(0, 4).map(([theme, qs]) => qs[0] && (
                  <blockquote key={theme} className="ri-quote"><small>{theme}</small>“{qs[0].text}”</blockquote>
                ))}
              </>
            ) : <p className="ri-sub">No earnings-call transcript was available for this company.</p>}
          </div>
        )}
      </section>

      <details className="ri-tool" open={!!sent}>
        <summary>Check the tone of any text</summary>
        <p className="ri-sub">Paste headlines or sentences, one per line (up to 50). Each is scored positive, neutral or negative.</p>
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
              Overall {sent.label} ({num(sent.net)}) · {sent.engine === 'finbert' ? 'scored by FinBERT, a model trained on financial text' : 'quick keyword read (the language model is still loading)'}
            </p>
            {sent.items.map((it, k) => (
              <div key={k} className="ri-news"><span className="ri-pill" style={{ background: colour(it.label) }}>{it.label} {num(it.net)}</span><div>{it.text}</div></div>
            ))}
          </>
        )}
      </details>
    </div>
  )
}
