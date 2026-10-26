import { useId, useState } from 'react'
import { instrumentPaths } from '../../api'
import { useMarket } from '../../hooks/useMarket'
import type { InstrumentSip } from '../../types'
import { fmtNum, fmtPct } from '../markets/format'
import { Provenance } from '../markets/Provenance'
import { fmtMoney } from './instruments'

const YEARS = [1, 3, 5, 10, 15, 20]
const pct = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? '–' : fmtPct(Math.abs(v) <= 1.5 ? v * 100 : v, 1)
const dd = (v: number | null | undefined) =>
  v == null || !Number.isFinite(v) ? '–' : `−${fmtNum(Math.abs(Math.abs(v) <= 1 ? v * 100 : v), 1)}%`

/** Growth line: solid accent = portfolio value, dashed muted = money put in. */
function Growth({ series }: { series: NonNullable<InstrumentSip['series']> }) {
  const pts = series.filter((s) => Number.isFinite(s.value) || Number.isFinite(s.invested))
  if (pts.length < 2) return null
  const max = Math.max(...pts.map((p) => Math.max(p.value ?? 0, p.invested ?? 0))) || 1
  const W = 200
  const H = 80
  const PAD = 4
  const x = (i: number) => PAD + (i / (pts.length - 1)) * (W - PAD * 2)
  const y = (v: number) => (H - PAD) - (v / max) * (H - PAD * 2)
  const path = (k: 'value' | 'invested') =>
    pts.map((p, i) => `${i ? 'L' : 'M'}${x(i).toFixed(1)} ${y(p[k] ?? 0).toFixed(1)}`).join('')

  return (
    <svg
      className="ix-growth"
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label="Simulated SIP: money put in (dashed) versus portfolio value (solid) over time"
    >
      {/* Filled area under the value line */}
      <defs>
        <linearGradient id="sip-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.18" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.01" />
        </linearGradient>
      </defs>
      <path
        d={`${path('value')} L${x(pts.length - 1).toFixed(1)} ${H} L${x(0).toFixed(1)} ${H} Z`}
        fill="url(#sip-grad)"
      />
      {/* Invested line (dashed) */}
      <path d={path('invested')} fill="none" stroke="var(--ink-muted)" strokeWidth="1.5" strokeDasharray="5 3" />
      {/* Value line */}
      <path d={path('value')} fill="none" stroke="var(--accent)" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  )
}

/** Historical SIP simulation. Everything shown is calculated by the API from past prices, and says so. */
export function SipPanel({ id }: { id: string }) {
  const uid = useId()
  const [monthly, setMonthly] = useState('5000')
  const [years, setYears] = useState(5)
  const [run, setRun] = useState({ monthly: 5000, years: 5 })
  const amount = Number(monthly)
  const valid = Number.isFinite(amount) && amount >= 100 && amount <= 10_000_000
  const res = useMarket<InstrumentSip>(instrumentPaths.sip(id, run.monthly, run.years), 0)
  const d = res.data
  const inr = 'INR'

  return (
    <section className="mk-card ix-sip" aria-labelledby={`${uid}-h`} aria-busy={res.loading}>
      <div className="sd-h">
        <h3 id={`${uid}-h`}>If you had invested every month</h3>
        <Provenance kind="calc" />
      </div>
      <form
        className="ix-sip-form"
        onSubmit={(e) => {
          e.preventDefault()
          if (valid) setRun({ monthly: amount, years })
        }}
      >
        <div className="ix-fld">
          <label htmlFor={`${uid}-m`}>Monthly amount (₹)</label>
          <input
            id={`${uid}-m`}
            className="ix-in"
            inputMode="numeric"
            value={monthly}
            aria-invalid={!valid}
            aria-describedby={valid ? undefined : `${uid}-e`}
            onChange={(e) => setMonthly(e.target.value.replace(/[^\d]/g, ''))}
          />
        </div>
        <div className="ix-fld">
          <label htmlFor={`${uid}-y`}>For</label>
          <select
            id={`${uid}-y`}
            className="ix-in"
            value={years}
            onChange={(e) => setYears(Number(e.target.value))}
          >
            {YEARS.map((y) => (
              <option key={y} value={y}>
                {y} {y === 1 ? 'year' : 'years'}
              </option>
            ))}
          </select>
        </div>
        <button type="submit" className="btn primary ix-sip-btn" disabled={!valid || res.loading}>
          {res.loading ? 'Running…' : 'Simulate'}
        </button>
      </form>

      {!valid && (
        <p id={`${uid}-e`} className="note" role="alert">
          Enter a monthly amount between ₹100 and ₹1,00,00,000.
        </p>
      )}

      {d ? (
        <>
          <dl className="ix-tiles num">
            <div>
              <dt>You put in</dt>
              <dd>{fmtMoney(d.invested, inr, 0)}</dd>
            </div>
            <div>
              <dt>It would be worth</dt>
              <dd>{fmtMoney(d.value, inr, 0)}</dd>
            </div>
            <div>
              <dt>XIRR</dt>
              <dd>{pct(d.xirr_pct)}</dd>
            </div>
            <div>
              <dt>CAGR</dt>
              <dd>{pct(d.cagr_pct)}</dd>
            </div>
            <div>
              <dt>Worst fall</dt>
              <dd>{dd(d.worst_drawdown_pct)}</dd>
            </div>
          </dl>
          {d.series && <Growth series={d.series} />}
          <p className="note">
            {d.caveat || 'Past performance does not predict future returns.'}
          </p>
        </>
      ) : res.loading ? (
        <span className="mk-skel" style={{ ['--h' as string]: '120px' }} role="status" aria-label="Running the simulation" />
      ) : (
        <p className="note" role="status">
          Could not run this simulation. There may not be enough price history for {run.years}{' '}
          {run.years === 1 ? 'year' : 'years'}; try a shorter period.
        </p>
      )}
    </section>
  )
}
