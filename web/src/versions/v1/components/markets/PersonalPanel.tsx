import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { ProfileState, ProfileSummary, SpendingInsightsData } from '../../types'
import { useMarket } from '../../hooks/useMarket'
import { Provenance } from './Provenance'
import { Delta } from './Delta'
import { Ring, arc } from './charts'
import { fmtPct } from './format'
import type { Overview } from './types'
import './panels.css'

interface Data {
  profile: ProfileState | null
  summary: ProfileSummary | null
  insights: SpendingInsightsData | null
}
// Fetched once per page load; each call may fail on its own and is then simply absent.
let cached: Promise<Data> | null = null
const loadAll = () =>
  (cached ??= Promise.allSettled([api.getProfile(), api.getProfileSummary(), api.getInsights()]).then(([p, s, i]) => ({
    profile: p.status === 'fulfilled' ? p.value : null,
    summary: s.status === 'fulfilled' ? s.value : null,
    insights: i.status === 'fulfilled' && i.value.available ? i.value : null,
  })))

const inr = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`
const CLASS_LABEL: Record<string, string> = { stocks: 'Stocks', mf: 'Mutual funds', fd: 'Fixed deposits', gold: 'Gold', cash: 'Cash', ppf: 'PPF', epf: 'EPF', nps: 'NPS', real_estate: 'Real estate' }
// Series colours live in theme-markets.css (--viz-1..9) so Night mode can re-tint them.
const COLORS = Array.from({ length: 9 }, (_, i) => `var(--viz-${i + 1})`)

function Card({ title, children, table, tableTitle }: { title: string; children: React.ReactNode; table?: React.ReactNode; tableTitle?: string }) {
  return (
    <section className="mk-card pp-card" aria-label={title}>
      <div className="sd-h"><h3>{title}</h3><Provenance kind="calc" /></div>
      {children}
      {table && (
        <details>
          <summary>View as table</summary>
          <table>
            <caption style={{ position: 'absolute', left: -9999 }}>{tableTitle ?? title}</caption>
            {table}
          </table>
        </details>
      )}
    </section>
  )
}

function AllocationDonut({ assets }: { assets: Record<string, number> }) {
  const rows = Object.entries(assets).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1])
  const total = rows.reduce((s, [, v]) => s + v, 0)
  const starts = rows.map((_, i) => (rows.slice(0, i).reduce((t, [, v]) => t + v, 0) / total) * 360)
  return (
    <Card
      title="Where your money sits"
      table={
        <>
          <thead><tr><th scope="col">Asset class</th><th scope="col">Amount</th><th scope="col">Share</th></tr></thead>
          <tbody>{rows.map(([k, v]) => <tr key={k} className="num"><td>{CLASS_LABEL[k] ?? k}</td><td>{inr(v)}</td><td>{((v / total) * 100).toFixed(1)}%</td></tr>)}</tbody>
        </>
      }
    >
      <div className="pp-donut">
        <svg width="140" height="140" viewBox="0 0 140 140" role="img" aria-label={`Total assets ${inr(total)}. ${rows.map(([k, v]) => `${CLASS_LABEL[k] ?? k} ${((v / total) * 100).toFixed(0)} percent`).join(', ')}`}>
          {rows.map(([k, v], i) => {
            const sweep = (v / total) * 360
            const d = arc(70, 70, 54, starts[i], starts[i] + Math.max(sweep - (rows.length > 1 ? 1.5 : 0), 0.5))
            return <path key={k} d={d} fill="none" stroke={COLORS[i % COLORS.length]} strokeWidth="18" />
          })}
          <text x="70" y="66" textAnchor="middle">Total</text>
          <text x="70" y="84" textAnchor="middle" className="num" style={{ fontSize: 13, fontWeight: 650, fill: 'var(--ink)' }}>{inr(total)}</text>
        </svg>
        <ul className="pp-legend">
          {rows.map(([k, v], i) => (
            <li key={k}><span className="sw" style={{ background: COLORS[i % COLORS.length] }} aria-hidden="true" />{CLASS_LABEL[k] ?? k} <span className="num">{((v / total) * 100).toFixed(0)}%</span><span className="amt num">{inr(v)}</span></li>
          ))}
        </ul>
      </div>
    </Card>
  )
}

function NetWorthCard({ s }: { s: NonNullable<ProfileSummary['snapshot']> }) {
  return (
    <Card title="Net worth">
      <div className="pp-big num">{inr(s.net_worth!)}</div>
      <p className="note num">
        {s.liquid != null && <>Liquid {inr(s.liquid)}. </>}
        {s.monthly_surplus != null && <>Monthly surplus {inr(s.monthly_surplus)}. </>}
        {s.foir != null && <>EMIs take {fmtPct(s.foir * 100, 0, false)} of income.</>}
      </p>
    </Card>
  )
}

function GoalsProgress({ goals, saved }: { goals: NonNullable<ProfileSummary['goals']>; saved: Record<string, number> }) {
  return (
    <Card
      title="Goals"
      table={
        <>
          <thead><tr><th scope="col">Goal</th><th scope="col">Saved</th><th scope="col">Target</th><th scope="col">Years</th><th scope="col">SIP/mo</th></tr></thead>
          <tbody>{goals.map((g, i) => <tr key={i} className="num"><td>{g.name}</td><td>{inr(saved[g.name] ?? 0)}</td><td>{inr(g.target)}</td><td>{g.years}</td><td>{g.sip_needed != null ? inr(g.sip_needed) : '–'}</td></tr>)}</tbody>
        </>
      }
    >
      {goals.map((g, i) => {
        const have = saved[g.name] ?? 0
        const pct = g.target > 0 ? Math.min(100, (have / g.target) * 100) : 0
        return (
          <div key={i}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 'var(--fs-2)' }}>
              <strong>{g.name}</strong><span className="num">{inr(have)} of {inr(g.target)} ({pct.toFixed(0)}%)</span>
            </div>
            <div className="pp-prog" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)} aria-label={`${g.name} progress`}><i style={{ width: `${pct}%` }} /></div>
            <p className="note num">{g.years} {g.years === 1 ? 'year' : 'years'} left{g.sip_needed != null ? `, SIP needed ${inr(g.sip_needed)}/month` : ''}{g.on_track === true ? ', on track' : g.on_track === false ? ', behind' : ''}</p>
          </div>
        )
      })}
    </Card>
  )
}

function CashFlowBars({ cf }: { cf: SpendingInsightsData['cashflow'] }) {
  const months = cf.by_month
  const income = cf.income_avg ?? 0
  const max = Math.max(income, ...months.map((m) => m.spend + m.emi), 1)
  const W = 300, H = 150, base = 120, gw = W / months.length
  const h = (v: number) => (v / max) * (base - 14)
  const mname = (m: string) => new Date(m + '-01T00:00:00Z').toLocaleString('en-IN', { month: 'short', timeZone: 'UTC' })
  return (
    <Card
      title="Monthly cash flow"
      table={
        <>
          <thead><tr><th scope="col">Month</th><th scope="col">Income (avg)</th><th scope="col">Spend</th><th scope="col">EMI</th><th scope="col">Left</th></tr></thead>
          <tbody>{months.map((m) => <tr key={m.month} className="num"><td>{m.month}</td><td>{income ? inr(income) : '–'}</td><td>{inr(m.spend)}</td><td>{inr(m.emi)}</td><td>{m.net != null ? inr(m.net) : '–'}</td></tr>)}</tbody>
        </>
      }
    >
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label={`Cash flow for ${months.length} months: ${months.map((m) => `${mname(m.month)} spend ${inr(m.spend)}, EMI ${inr(m.emi)}${m.net != null ? `, left ${inr(m.net)}` : ''}`).join('; ')}. Average income ${income ? inr(income) : 'unknown'}.`}>
        <line x1="0" x2={W} y1={base} y2={base} stroke="var(--border-strong)" />
        {months.map((m, i) => {
          const x = i * gw + gw / 2
          const bw = Math.min(22, gw / 4)
          return (
            <g key={m.month}>
              {income > 0 && <rect x={x - bw * 1.6} y={base - h(income)} width={bw} height={h(income)} fill="var(--accent)" />}
              <rect x={x - bw * 0.5} y={base - h(m.spend)} width={bw} height={h(m.spend)} fill="var(--viz-2)" />
              <rect x={x + bw * 0.6} y={base - h(m.emi)} width={bw} height={h(m.emi)} fill="var(--viz-3)" />
              <text x={x} y={base + 13} textAnchor="middle">{mname(m.month)}</text>
              {m.net != null && <text x={x} y={base + 26} textAnchor="middle" style={{ fill: 'var(--ink)' }}>{m.net >= 0 ? 'left' : 'short'} {inr(Math.abs(m.net))}</text>}
            </g>
          )
        })}
      </svg>
      <ul className="pp-legend" style={{ gridAutoFlow: 'column', gridAutoColumns: 'max-content', gap: 12 }}>
        <li><span className="sw" style={{ background: 'var(--accent)' }} aria-hidden="true" />Income (average)</li>
        <li><span className="sw" style={{ background: 'var(--viz-2)' }} aria-hidden="true" />Spend</li>
        <li><span className="sw" style={{ background: 'var(--viz-3)' }} aria-hidden="true" />EMI</li>
      </ul>
    </Card>
  )
}

function HealthRing({ h }: { h: NonNullable<ProfileSummary['health']> }) {
  const prov = h.coverage != null && h.coverage < 0.6
  return (
    <Card
      title="Financial health"
      table={
        <>
          <thead><tr><th scope="col">Check</th><th scope="col">Weight</th><th scope="col">Score</th></tr></thead>
          <tbody>{h.breakdown.map((b) => <tr key={b.name} className="num"><td>{b.name}</td><td>{b.weight}</td><td>{b.sub != null ? Math.round(b.sub * 100) : 'needs data'}</td></tr>)}</tbody>
        </>
      }
    >
      <div className="pp-donut">
        <Ring value={h.score} label={`Financial health score ${Math.round(h.score)} out of 100${prov ? ', provisional' : ''}`}>
          <text x="48" y="56" textAnchor="middle" style={{ fontSize: 24, fontWeight: 650, fill: 'var(--ink)' }}>{Math.round(h.score)}</text>
        </Ring>
        <p className="note" style={{ flex: 1, minWidth: 140 }}>
          Out of 100.{prov && <> Provisional: only {Math.round((h.coverage ?? 0) * 100)}% of the checks have your data yet. Add more details to firm it up.</>}
        </p>
      </div>
    </Card>
  )
}

function EquityToday({ equity }: { equity: number }) {
  const { data } = useMarket<Overview>('/api/markets/overview', 60000)
  const n = data?.items.find((i) => i.symbol === '^NSEI')
  if (!n) return null
  const est = equity * (1 + n.change_pct / 100)
  return (
    <section className="mk-card pp-card" aria-label="Your equity today">
      <div className="sd-h"><h3>Your equity today</h3><Provenance kind="calc" /></div>
      <p style={{ margin: 0 }} className="num">
        ≈ {inr(est)} if it moved with Nifty (<Delta value={n.change_pct} />), a change of {inr(est - equity)}.
      </p>
      <p className="note">ARIA does not know your individual holdings. This applies the Nifty move to your stocks and mutual funds total.</p>
    </section>
  )
}

export function PersonalPanel({ onAsk }: { onAsk: (q: string) => void }) {
  const [d, setD] = useState<Data | null>(null)
  useEffect(() => {
    let live = true
    loadAll().then((x) => live && setD(x))
    return () => {
      live = false
    }
  }, [])

  if (!d) return <section className="pp" aria-label="Your money" aria-busy="true"><h2 style={{ margin: 0, fontSize: 'var(--fs-4)' }}>Your money</h2><span className="mk-skel" style={{ '--h': '180px' } as React.CSSProperties} /></section>

  const p = d.profile?.profile
  const assets = Object.fromEntries(Object.entries(p?.assets ?? {}).filter(([, v]) => typeof v === 'number' && v > 0)) as Record<string, number>
  const snap = d.summary?.snapshot
  const goals = d.summary?.goals ?? []
  const saved = Object.fromEntries((p?.goals ?? []).map((g) => [g.name ?? '', g.saved ?? 0]))
  const equity = (assets.stocks ?? 0) + (assets.mf ?? 0)
  const cards = [
    Object.keys(assets).length > 0 && <AllocationDonut key="a" assets={assets} />,
    snap?.net_worth != null && <NetWorthCard key="n" s={snap} />,
    goals.length > 0 && <GoalsProgress key="g" goals={goals} saved={saved} />,
    d.insights && d.insights.cashflow.by_month.length > 0 && <CashFlowBars key="c" cf={d.insights.cashflow} />,
    d.summary?.health && <HealthRing key="h" h={d.summary.health} />,
  ].filter(Boolean)

  return (
    <section className="pp" aria-label="Your money">
      <h2 style={{ margin: 0, fontSize: 'var(--fs-4)' }}>Your money</h2>
      {cards.length === 0 ? (
        <div className="mk-card pp-empty">
          <p style={{ margin: 0 }}>Add your income, assets and goals to see your own dashboard.</p>
          <button className="btn primary" type="button" onClick={() => onAsk('Help me set up my profile')}>Help me set up my profile</button>
          <a href="#/profile">Or fill it in on the Profile page</a>
        </div>
      ) : (
        <>
          <div className="pp-grid">{cards}</div>
          {equity > 0 && <EquityToday equity={equity} />}
        </>
      )}
    </section>
  )
}
