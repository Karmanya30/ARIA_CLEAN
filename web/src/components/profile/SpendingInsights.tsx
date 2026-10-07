import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { SpendingInsightsData as Data } from '../../types'

const inr = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`
const short = (n: number) => (n >= 100000 ? `₹${(n / 100000).toFixed(1)}L` : n >= 1000 ? `₹${Math.round(n / 1000)}k` : inr(n))
const pct = (v: number) => `${Math.round(v)}%` // the insights API reports percentages (39.4), not fractions
const nice = (k: string) => k.replace(/_/g, ' ')
const mon = (d: string) => new Date(d).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })
const monthLabel = (m: string) => new Date(`${m}-01`).toLocaleDateString('en-IN', { month: 'short', year: '2-digit' })
const ASKS = ['Analyse my spending', 'Where can I cut my spending?', 'What subscriptions do I have?', 'Any unusual transactions?', 'How much did I spend on food last month?']
const ORDER = { high: 0, medium: 1, low: 2 }

/** Chips that jump to Chat and send the question. */
export function AskChips({ onAsk, max = 4 }: { onAsk?: (q: string) => void; max?: number }) {
  if (!onAsk) return null
  return (
    <div className="si-chips" role="group" aria-label="Ask in chat">
      <span>Ask in chat:</span>
      {ASKS.slice(0, max).map((q) => <button key={q} type="button" className="si-chip" onClick={() => onAsk(q)}>{q}</button>)}
    </div>
  )
}

/** Spending insights computed server-side from the user's imported transactions. A changed `refreshKey` forces a refetch. */
export function SpendingInsights({ refreshKey, onAsk }: { refreshKey: number; onAsk?: (q: string) => void }) {
  const [data, setData] = useState<Data | null>(null)
  const [err, setErr] = useState(false)
  const [open, setOpen] = useState(true)

  useEffect(() => {
    let live = true
    api.getInsights().then((d) => { if (live) { setData(d); setErr(false) } }).catch(() => { if (live) setErr(true) })
    return () => { live = false }
  }, [refreshKey])

  const loading = !data && !err
  let body
  if (loading) body = <div className="si-skel" aria-hidden="true" />
  else if (err) body = <p className="banner-info" role="alert">Could not load spending insights right now. They will return on the next refresh.</p>
  else if (!data || !data.available) body = <p className="banner-info">{data?.reason || 'No transactions yet.'} Upload a statement below to see where your money goes.</p>
  else body = <Body d={data} onAsk={onAsk} />

  return (
    <section className="card si" aria-labelledby="si-h" aria-busy={loading}>
      <div className="si-head">
        <h3 id="si-h">Spending insights</h3>
        {data?.available && <span className="si-period">{mon(data.period.from)}–{mon(data.period.to)} · {data.period.months} month(s)</span>}
        <button type="button" className="btn si-toggle" aria-expanded={open} aria-controls="si-body" onClick={() => setOpen((o) => !o)}>{open ? 'Hide' : 'Show'}</button>
      </div>
      <div id="si-body" hidden={!open}>{body}</div>
    </section>
  )
}

function Body({ d, onAsk }: { d: Data; onAsk?: (q: string) => void }) {
  const { cashflow: c } = d
  const top = d.categories[0]
  const headline = [
    `You spend about ${short(c.spend_avg + c.emi_avg)} a month`,
    top && `${pct(top.share_of_spend)} goes to ${nice(top.name)}`,
    c.savings_rate != null && `savings rate ${pct(c.savings_rate)}`,
  ].filter(Boolean).join('; ')
  const maxBar = Math.max(1, ...c.by_month.map((m) => m.spend + m.emi))
  const maxCat = Math.max(1, ...d.categories.map((x) => x.monthly_avg))
  const tips = [...d.suggestions].sort((a, b) => ORDER[a.priority] - ORDER[b.priority])
  const total = tips.reduce((s, t) => s + (t.saving_per_month ?? 0), 0)

  return (
    <>
      <p className="si-headline">{headline}.</p>
      <p className="si-note">Calculated from your uploaded transactions, not AI estimates. Benchmarks are rules of thumb, not advice.</p>
      <AskChips onAsk={onAsk} />

      <h4>Spending by month</h4>
      <div className="si-chart" role="img" aria-label={`Monthly spending: ${c.by_month.map((m) => `${monthLabel(m.month)} ${inr(m.spend + m.emi)}`).join(', ')}`}>
        {c.by_month.map((m) => (
          <div key={m.month} className="si-col" title={`${monthLabel(m.month)}: ${inr(m.spend)} spending + ${inr(m.emi)} EMI`}>
            <div className="si-stack" style={{ height: `${((m.spend + m.emi) / maxBar) * 100}%` }}>
              <i className="si-emi" style={{ flexGrow: m.emi }} />
              <i className="si-spend" style={{ flexGrow: m.spend }} />
            </div>
            <span>{monthLabel(m.month)}</span>
          </div>
        ))}
      </div>
      <p className="si-legend"><i className="si-spend" /> Spending <i className="si-emi" /> EMIs</p>
      <table className="sr-only">
        <caption>Spending and EMIs per month</caption>
        <thead><tr><th>Month</th><th>Spending</th><th>EMI</th></tr></thead>
        <tbody>{c.by_month.map((m) => <tr key={m.month}><td>{monthLabel(m.month)}</td><td>{inr(m.spend)}</td><td>{inr(m.emi)}</td></tr>)}</tbody>
      </table>

      <h4>Where it goes (monthly average)</h4>
      <div className="ri-bars">
        {d.categories.map((x) => (
          <div key={x.name} className="ri-bar">
            <span>{nice(x.name)}</span>
            <div className="ri-track"><div style={{ width: `${Math.round((x.monthly_avg / maxCat) * 100)}%`, background: x.over_benchmark ? 'var(--amber)' : 'var(--accent)' }} /></div>
            <b>{inr(x.monthly_avg)}</b>
            <small className="si-meta">
              {pct(x.share_of_spend)} of spending
              {x.trend_pct != null && Math.abs(x.trend_pct) >= 1 && (
                <span aria-label={`${x.trend_pct > 0 ? 'up' : 'down'} ${Math.abs(Math.round(x.trend_pct))} percent`}> · {x.trend_pct > 0 ? '▲' : '▼'} {Math.abs(Math.round(x.trend_pct))}%</span>
              )}
              {x.over_benchmark && x.benchmark_pct != null && <span className="si-badge">above the usual ~{Math.round(x.benchmark_pct)}% of income</span>}
            </small>
          </div>
        ))}
      </div>

      {d.recurring.length > 0 && (
        <>
          <h4>Recurring payments <small>Check you still use these</small></h4>
          <ul className="si-list">
            {d.recurring.map((r) => (
              <li key={r.merchant}><b>{r.merchant}</b> <span>{inr(r.amount)}/month · {r.months} months · {inr(r.amount * 12)} a year</span></li>
            ))}
          </ul>
        </>
      )}

      {d.unusual.length > 0 && (
        <>
          <h4>Unusual charges <small>Verify these are yours</small></h4>
          <ul className="si-list">
            {d.unusual.map((u, i) => (
              <li key={i}><b>{u.merchant}</b> <span>{inr(u.amount)} · {u.date}</span><br /><small>{u.why}</small></li>
            ))}
          </ul>
        </>
      )}

      {d.top_merchants.length > 0 && (
        <>
          <h4>Top merchants</h4>
          <ul className="si-list">
            {d.top_merchants.map((m) => <li key={m.merchant}><b>{m.merchant}</b> <span>{inr(m.total)} · {m.count} payment(s)</span></li>)}
          </ul>
        </>
      )}

      {tips.length > 0 && (
        <>
          <h4>Ways to save</h4>
          <div className="si-tips">
            {tips.map((t) => (
              <div key={t.title} className={`si-tip si-${t.priority}`}>
                <b>{t.title}</b>
                <p>{t.detail}</p>
                {t.saving_per_month != null && <strong>Save about {inr(t.saving_per_month)} a month</strong>}
                <small>{t.priority} priority</small>
              </div>
            ))}
          </div>
          {total > 0 && <p className="si-total">Total potential saving: about {inr(total)} a month ({inr(total * 12)} a year).</p>}
        </>
      )}
      {d.notes.length > 0 && <ul className="si-note">{d.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
    </>
  )
}
