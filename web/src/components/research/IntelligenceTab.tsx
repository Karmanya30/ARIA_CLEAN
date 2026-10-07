import { useState } from 'react'
import { api } from '../../api'
import type { CompanyIntel, SentimentResult } from '../../api'
import './ResearchTab.css'
import './IntelligenceTab.css'

const TONE: Record<string, string> = {
  buy: 'var(--green)', hold: 'var(--amber)', sell: 'var(--red)',
  positive: 'var(--green)', neutral: 'var(--amber)', negative: 'var(--red)',
  high: 'var(--red)', medium: 'var(--amber)', low: 'var(--ink-faint)',
}
const colour = (k: string) => TONE[(k ?? '').toLowerCase()] ?? 'var(--ink-faint)'
const bandColour = (score: number) => (score >= 65 ? 'var(--green)' : score >= 40 ? 'var(--amber)' : 'var(--red)')
const num = (n: number) => (n > 0 ? '+' : '') + n.toFixed(2)
const errMsg = (e: unknown) => (e instanceof Error ? e.message : 'Request failed')

/** Standalone company-intelligence score + free-text sentiment, straight from the backend. */
export function IntelligenceTab() {
  const [q, setQ] = useState('')
  const [data, setData] = useState<CompanyIntel | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [text, setText] = useState('')
  const [sent, setSent] = useState<SentimentResult | null>(null)
  const [sBusy, setSBusy] = useState(false)
  const [sError, setSError] = useState<string | null>(null)

  async function run<T>(fn: () => Promise<T>, set: (v: T) => void, setLoading: (b: boolean) => void, setErr: (e: string | null) => void) {
    setLoading(true)
    setErr(null)
    try {
      set(await fn())
    } catch (e) {
      setErr(errMsg(e))
    } finally {
      setLoading(false)
    }
  }

  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean)
  const i = data?.intelligence

  return (
    <div className="ri">
      <section>
        <h2>Company intelligence</h2>
        <form className="ri-form" onSubmit={(e) => { e.preventDefault(); if (q.trim()) run(() => api.companyIntel(q.trim()), setData, setBusy, setError) }}>
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Company name or symbol, e.g. Infosys" aria-label="Company" />
          <button type="submit" disabled={busy || !q.trim()}>{busy ? 'Analysing…' : 'Analyse'}</button>
        </form>
        {busy && <p className="rt-hint">Gathering data and news… the first run can take up to 30 seconds.</p>}
        {error && <p className="rt-error">{error}</p>}
        {data && i && (
          <div>
            <p>
              <strong>{data.company.name}</strong> ({data.company.symbol}){' '}
              <span className="ri-score" style={{ background: bandColour(i.score) }}>{Math.round(i.score)}</span> {i.band}
            </p>
            {i.low_evidence && <p className="rt-warn">Low evidence: coverage is {Math.round(i.coverage * 100)}%, treat the score with caution.</p>}
            <div className="ri-box">
              <table className="ri-table">
                <thead><tr><th>Component</th><th>Weight</th><th>Value</th></tr></thead>
                <tbody>{i.components.map((c) => <tr key={c.name}><td>{c.name}</td><td>{c.weight}</td><td>{Math.round(c.value * 100)}%</td></tr>)}</tbody>
              </table>
            </div>
            <h2>Pillars</h2>
            {data.scorecard.pillars.map((p) => (
              <div key={p.name} className="ri-box">
                <span className="rt-chip" style={{ background: colour(p.rating) }}>{p.rating}</span> <strong>{p.name}</strong> ({p.points} pts)
                {p.reasons.map((r, n) => <div key={n} className="rt-sub">{Number(r.sign) > 0 ? "▲" : Number(r.sign) < 0 ? "▼" : "●"} {r.text}</div>)}
              </div>
            ))}
            {data.scorecard.overlay?.reading && <p className="rt-hint">{data.scorecard.overlay.tone}: {data.scorecard.overlay.reading}</p>}
            {i.divergences.length > 0 && <h2>Divergence flags</h2>}
            {i.divergences.map((d) => (
              <div key={d.id} className="ri-box" style={{ borderLeft: `4px solid ${colour(d.severity)}` }}>
                <strong>{d.severity}</strong> {d.text}
                <div className="rt-sub">{d.evidence}</div>
              </div>
            ))}
            {data.news.length > 0 && <h2>Headlines</h2>}
            {data.news.slice(0, 8).map((n, k) => (
              <div key={k} className="ri-box">
                <span className="rt-chip" style={{ background: colour(n.direction) }}>{n.direction} {num(n.net)}</span> {n.title}
                <div className="rt-sub">{n.source} · {n.date}</div>
              </div>
            ))}
            <p className="rt-hint">
              {data.call.available ? `Earnings call (${data.call.period}): net tone ${num(data.call.net ?? 0)}${data.call.themes?.length ? ` · ${data.call.themes.join(', ')}` : ''}` : 'No earnings-call transcript available.'}
            </p>
          </div>
        )}
      </section>
      <section>
        <h2>Sentiment</h2>
        <form className="ri-form" onSubmit={(e) => { e.preventDefault(); if (lines.length) run(() => api.sentiment(lines.slice(0, 50)), setSent, setSBusy, setSError) }}>
          <textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="One text per line (max 50)" aria-label="Texts" />
          <button type="submit" disabled={sBusy || !lines.length}>{sBusy ? 'Scoring…' : 'Score'}</button>
        </form>
        {lines.length > 50 && <p className="rt-hint">Only the first 50 lines are scored.</p>}
        {sError && <p className="rt-error">{sError}</p>}
        {sent && (
          <div>
            <p className="rt-hint">Engine: {sent.engine} · overall {sent.label} ({num(sent.net)})</p>
            {sent.items.map((it, k) => (
              <div key={k} className="ri-box">
                <span className="rt-chip" style={{ background: colour(it.label) }}>{it.label} {num(it.net)}</span> {it.text}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  )
}
