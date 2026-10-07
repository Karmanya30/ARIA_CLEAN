import { useCallback, useEffect, useId, useRef, useState } from 'react'
import { api, ownerId } from '../../api'
import type { ProfileState, ProfileSummary, Transaction } from '../../types'
import { StatementUpload } from './StatementUpload'
import './ProfileTab.css'

const CATEGORIES = ['housing', 'food', 'transport', 'utilities', 'emi', 'entertainment', 'medical', 'other']
const CHANNELS = ['', 'upi', 'card', 'cash', 'netbanking']

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type D = Record<string, any>
type Kind = 'money' | 'num' | 'text' | 'select'
type Opts = [string, string][]
const o = (...v: string[]): Opts => v.map((x) => [x, x.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())])

const STEPS = [
  { name: 'About you', keys: ['age', 'city', 'city_tier', 'employment', 'marital_status', 'dependents'], why: 'Used to pick sensible benchmarks, like how big your emergency fund should be.' },
  { name: 'Income & expenses', keys: ['monthly_income', 'income_stability', 'expenses'], why: 'Used to check what you can afford to save, invest or borrow each month.' },
  { name: 'Assets', keys: ['assets'], why: 'Used to work out your net worth and how much you could reach in an emergency.' },
  { name: 'Loans & insurance', keys: ['loans', 'credit_card_outstanding', 'term_cover', 'health_cover'], why: 'Used to see how much of your income EMIs take and whether your family is protected.' },
  { name: 'Goals & preferences', keys: ['goals', 'risk_tolerance', 'horizon_years', 'tax_regime', 'used_80c', 'used_80d'], why: 'Used to size monthly SIPs for each goal and pick the better tax regime.' },
]

const META: Record<string, { label: string; kind?: Kind; opts?: Opts; range?: [number, number]; hint?: string }> = {
  age: { label: 'Age', kind: 'num', range: [18, 100] },
  city: { label: 'City', kind: 'text' },
  city_tier: { label: 'City type', kind: 'select', opts: [['1', 'Metro (tier 1)'], ['2', 'Large city (tier 2)'], ['3', 'Smaller town (tier 3)']] },
  employment: { label: 'Work', kind: 'select', opts: o('salaried', 'self_employed', 'business', 'retired', 'student') },
  marital_status: { label: 'Marital status', kind: 'select', opts: o('single', 'married', 'divorced', 'widowed') },
  dependents: { label: 'People who depend on you', kind: 'num', range: [0, 15], hint: 'Children, parents or others you support.' },
  monthly_income: { label: 'Monthly take-home income', kind: 'money' },
  income_stability: { label: 'Income pattern', kind: 'select', opts: o('stable', 'variable') },
  expenses: { label: 'Monthly expenses' },
  assets: { label: 'What you own' },
  loans: { label: 'Loans' },
  existing_emi: { label: 'Monthly EMIs (total)', kind: 'money' },
  emergency_fund_months: { label: 'Emergency fund (months)', kind: 'num', range: [0, 120] },
  credit_card_outstanding: { label: 'Credit card dues', kind: 'money' },
  term_cover: { label: 'Term life cover', kind: 'money', hint: 'Total sum assured.' },
  health_cover: { label: 'Health cover', kind: 'money', hint: 'Total sum insured across policies.' },
  goals: { label: 'Goals' },
  risk_tolerance: { label: 'Comfort with risk', kind: 'select', opts: o('Conservative', 'Moderate', 'Aggressive') },
  horizon_years: { label: 'Investing horizon (years)', kind: 'num', range: [1, 60] },
  tax_regime: { label: 'Tax regime', kind: 'select', opts: o('old', 'new') },
  used_80c: { label: '80C used this year', kind: 'money', hint: 'EPF, PPF, ELSS, life insurance etc. (max 1,50,000).' },
  used_80d: { label: '80D used this year', kind: 'money', hint: 'Health insurance premiums.' },
}
const EXP = ['food', 'rent', 'transport', 'utilities', 'entertainment', 'health', 'education', 'other']
const AST = ['cash', 'fd', 'mf', 'stocks', 'gold', 'epf', 'ppf', 'nps', 'real_estate']
const AST_LABEL: Record<string, string> = { cash: 'Cash & savings', fd: 'Fixed deposits', mf: 'Mutual funds', stocks: 'Stocks', gold: 'Gold', epf: 'EPF', ppf: 'PPF', nps: 'NPS', real_estate: 'Real estate' }
const RANGE: Record<string, [number, number]> = { rate_pct: [0, 50], months_left: [0, 600], years: [1, 60] }
const ROW_FIELDS: Record<string, [string, string, Kind, Opts?][]> = {
  loans: [
    ['kind', 'Type', 'select', o('home', 'car', 'personal', 'education', 'other')],
    ['emi', 'EMI per month', 'money'],
    ['rate_pct', 'Interest rate (%)', 'num'],
    ['months_left', 'Months left', 'num'],
    ['outstanding', 'Still owed (optional)', 'money'],
  ],
  goals: [
    ['name', 'Goal', 'text'],
    ['target', 'Target amount (today’s value)', 'money'],
    ['years', 'In how many years', 'num'],
    ['priority', 'Priority', 'select', [['1', 'High'], ['2', 'Medium'], ['3', 'Low']]],
    ['saved', 'Already saved', 'money'],
  ],
}
const MONEY_KEYS = new Set(['monthly_income', 'credit_card_outstanding', 'term_cover', 'health_cover', 'used_80c', 'used_80d'])

const label = (k: string) => META[k]?.label ?? AST_LABEL[k] ?? k.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())
const stepOf = (k: string) => Math.max(0, STEPS.findIndex((s) => s.keys.includes(k.split('.')[0])))

/** Rs 1.2L / 3.4Cr style, Indian grouping below a lakh. */
function inr(n: number): string {
  const a = Math.abs(n), s = n < 0 ? '-' : ''
  if (a >= 1e7) return `${s}₹${+(a / 1e7).toFixed(2)}Cr`
  if (a >= 1e5) return `${s}₹${+(a / 1e5).toFixed(2)}L`
  return `${s}₹${Math.round(a).toLocaleString('en-IN')}`
}
const sum = (x: D) => Object.values(x).reduce((t: number, v) => t + (Number(v) || 0), 0)

function show(k: string, v: unknown): string {
  if (Array.isArray(v)) return `${v.length} ${v.length === 1 ? 'item' : 'items'}`
  if (v && typeof v === 'object') return `${Object.keys(v).length} entries, ${inr(sum(v as D))} total`
  if (typeof v === 'number') return MONEY_KEYS.has(k) || k.includes('.') ? inr(v) : k === 'city_tier' ? `Tier ${v}` : String(v)
  const opt = META[k]?.opts?.find(([x]) => x === String(v))
  return opt ? opt[1] : String(v ?? '')
}

const tone = (p: number) => (p >= 70 ? 'var(--green)' : p >= 40 ? 'var(--amber)' : 'var(--red)')

function Inp({ label: l, hint, kind = 'text', opts, range, value, onChange, small }: {
  label: string; hint?: string; kind?: Kind; opts?: Opts; range?: [number, number]; value: unknown; onChange: (v: unknown) => void; small?: boolean
}) {
  const id = useId()
  const v = value as number | string | undefined
  const bad = typeof v === 'number' && range && (v < range[0] || v > range[1]) ? `Enter a value between ${range[0]} and ${range[1]}.` : ''
  const common = { id, className: 'input', 'aria-invalid': !!bad, 'aria-describedby': `${id}-h` }
  return (
    <div className="field">
      <label htmlFor={id}>{l}</label>
      {kind === 'select' ? (
        <select {...common} value={v == null ? '' : String(v)} onChange={(e) => onChange(e.target.value === '' ? undefined : isNaN(+e.target.value) ? e.target.value : +e.target.value)}>
          <option value="">{small ? '-' : 'Skip / not sure'}</option>
          {opts?.map(([x, t]) => <option key={x} value={x}>{t}</option>)}
        </select>
      ) : kind === 'money' ? (
        <div className="pf-money">
          <span aria-hidden="true">₹</span>
          <input {...common} inputMode="numeric" autoComplete="off" placeholder="Optional" value={v == null ? '' : Number(v).toLocaleString('en-IN')}
            onChange={(e) => { const d = e.target.value.replace(/\D/g, ''); onChange(d === '' ? undefined : Number(d)) }} />
        </div>
      ) : kind === 'num' ? (
        <input {...common} type="number" inputMode="decimal" placeholder="Optional" min={range?.[0]} max={range?.[1]} value={v ?? ''} onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))} />
      ) : (
        <input {...common} placeholder="Optional" value={v ?? ''} onChange={(e) => onChange(e.target.value || undefined)} />
      )}
      <small id={`${id}-h`} className={bad ? 'pf-err' : 'pf-hint'}>{bad || hint || ''}</small>
    </div>
  )
}

/** Normalise a draft value for saving: drop blanks; empty -> null (= forget). */
function clean(v: unknown): unknown {
  if (Array.isArray(v)) {
    const rows = v.map((r) => Object.fromEntries(Object.entries(r).filter(([, x]) => x != null && x !== ''))).filter((r) => Object.keys(r).length)
    return rows.length ? rows : null
  }
  if (v && typeof v === 'object') {
    const e = Object.fromEntries(Object.entries(v).filter(([, x]) => x != null && x !== ''))
    return Object.keys(e).length ? e : null
  }
  return v == null || v === '' ? null : v
}

export function ProfileTab() {
  const [state, setState] = useState<ProfileState | null>(null)
  const [summary, setSummary] = useState<ProfileSummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [d, setD] = useState<D>({})
  const [step, setStep] = useState(0)
  const [msg, setMsg] = useState('')
  const [busy, setBusy] = useState(false)
  const [edit, setEdit] = useState<{ k: string; v: unknown } | null>(null)
  const head = useRef<HTMLHeadingElement>(null)
  const form = useRef<HTMLElement>(null)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [txnForm, setTxnForm] = useState({ date: new Date().toISOString().slice(0, 10), category: 'housing', amount: 0, merchant: '', channel: '' })
  const owner = ownerId()

  const load = useCallback(async (first = false, resetForm = false) => {
    if (first) setLoading(true)
    try {
      const s = await api.getProfile()
      if (!s || typeof s.profile !== 'object') throw new Error('Unexpected response')
      setState(s)
      if (first || resetForm) setD(structuredClone(s.profile ?? {}))
      setError('')
      api.getProfileSummary().then(setSummary).catch(() => setSummary(null))
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not load your profile.')
    }
    setLoading(false)
  }, [])

  useEffect(() => { load(true); api.getTransactions(owner).then(setTransactions).catch(() => setTransactions([])) }, [load, owner])

  const profile: D = state?.profile ?? {}
  const sources = state?.sources ?? {}
  const hasData = Object.values(profile).some((v) => v != null)
  const pct = Math.max(0, Math.min(100, state?.completeness?.pct ?? 0))
  const missing = state?.completeness?.missing ?? []

  function jump(i: number) {
    setStep(i)
    setMsg('')
    requestAnimationFrame(() => { head.current?.focus(); head.current?.scrollIntoView({ block: 'start', behavior: 'smooth' }) })
  }

  async function post(patch: D) {
    const s = await api.saveProfile(patch)
    if (s?.profile) { setState(s); api.getProfileSummary().then(setSummary).catch(() => {}) } else await load()
  }

  async function saveStep() {
    const bad = form.current?.querySelector<HTMLElement>('[aria-invalid="true"]')
    if (bad) { bad.focus(); setMsg('Please fix the highlighted field first, or clear it to skip.'); return }
    const patch: D = {}
    for (const k of STEPS[step].keys) {
      const c = clean(d[k])
      if (JSON.stringify(c) !== JSON.stringify(profile[k] ?? null)) patch[k] = c
    }
    setBusy(true)
    try {
      if (Object.keys(patch).length) await post(patch)
      if (step < STEPS.length - 1) jump(step + 1)
      else setMsg('Saved. ARIA will use this in every answer.')
    } catch (e) {
      setMsg(`Could not save: ${e instanceof Error ? e.message : 'try again'}`)
    }
    setBusy(false)
  }

  async function forget(k: string) {
    if (!window.confirm(`Forget "${label(k)}"?`)) return
    const [top, sub] = k.split('.')
    let patch: D = { [top]: null }
    if (sub) {
      const rest = Object.fromEntries(Object.entries(profile[top] ?? {}).filter(([x]) => x !== sub))
      patch = { [top]: Object.keys(rest).length ? rest : null }
    }
    try { await post(patch); setD((p) => ({ ...p, [top]: patch[top] ?? undefined })) } catch (e) { setMsg(`Could not delete: ${e instanceof Error ? e.message : ''}`) }
  }

  async function saveEdit() {
    if (!edit) return
    const v = edit.v === '' || edit.v == null ? null : edit.v
    try { await post({ [edit.k]: v }); setD((p) => ({ ...p, [edit.k]: v ?? undefined })); setEdit(null) } catch (e) { setMsg(`Could not save: ${e instanceof Error ? e.message : ''}`) }
  }

  async function deleteAll() {
    if (!window.confirm('Delete all your finance data (profile and transactions)? This cannot be undone.')) return
    try {
      await api.deleteProfile()
      await api.clearTransactions(owner).catch(() => {})
      setD({}); setSummary(null); setTransactions([]); setStep(0); setMsg('')
      await load(true)
    } catch (e) { setMsg(`Could not delete: ${e instanceof Error ? e.message : 'try again'}`) }
  }

  const set = (k: string, v: unknown) => { setD((p) => ({ ...p, [k]: v })); setMsg('') }
  const F = (k: string) => <Inp key={k} {...META[k]} value={d[k]} onChange={(v) => set(k, v)} />
  const money = (g: string, keys: string[]) => (
    <div className="form-grid">{keys.map((k) => <Inp key={k} label={label(k)} kind="money" value={d[g]?.[k]} onChange={(v) => set(g, { ...(d[g] ?? {}), [k]: v })} />)}</div>
  )
  const rows = (g: 'loans' | 'goals') => {
    const list: D[] = d[g] ?? []
    const upd = (i: number, k: string, v: unknown) => set(g, list.map((r, j) => (j === i ? { ...r, [k]: v } : r)))
    return (
      <div className="pf-rows">
        {list.map((r, i) => (
          <fieldset key={i} className="pf-row">
            <legend>{g === 'loans' ? 'Loan' : 'Goal'} {i + 1}</legend>
            <div className="form-grid">
              {ROW_FIELDS[g].map(([k, l, kind, opts]) => (
                <Inp key={k} label={l} kind={kind} opts={opts} range={RANGE[k]} value={r[k]} onChange={(v) => upd(i, k, v)} />
              ))}
            </div>
            <button type="button" className="btn pf-link" onClick={() => set(g, list.filter((_, j) => j !== i))}>Remove</button>
          </fieldset>
        ))}
        <button type="button" className="btn" onClick={() => set(g, [...list, {}])}>+ Add {g === 'loans' ? 'a loan' : 'a goal'}</button>
      </div>
    )
  }

  const snap = summary?.snapshot
  const health = summary?.health
  // savings_rate may arrive as a fraction (0.25) or a percent (25); treat |x| <= 1.5 as a fraction.
  const pctVal = (x: number) => `${Math.round(Math.abs(x) <= 1.5 ? x * 100 : x)}%`
  const stats: [string, string | null, string][] = [
    ['Net worth', snap?.net_worth != null ? inr(snap.net_worth) : null, 'Add assets and loans'],
    ['Monthly surplus', snap?.monthly_surplus != null ? inr(snap.monthly_surplus) : null, 'Add income and expenses'],
    ['Savings rate', snap?.savings_rate != null ? pctVal(snap.savings_rate) : null, 'Add income and expenses'],
    ['Emergency fund', snap?.emergency_months != null ? `${+snap.emergency_months.toFixed(1)} months` : null, 'Add savings and expenses'],
  ]

async function addTransaction() {
    if (txnForm.amount <= 0) return
    await api.addTransaction(owner, {
      date: txnForm.date,
      category: txnForm.category,
      amount: txnForm.amount,
      merchant: txnForm.merchant || null,
      channel: txnForm.channel || null,
    })
    setTxnForm((f) => ({ ...f, amount: 0, merchant: '' }))
    api.getTransactions(owner).then(setTransactions)
  }

  async function loadSample() {
    await api.loadSampleTransactions(owner)
    api.getTransactions(owner).then(setTransactions)
  }

  async function clearAll() {
    await api.clearTransactions(owner)
    api.getTransactions(owner).then(setTransactions)
  }

  if (loading) return <div className="pf" aria-busy="true"><h1>Your Finance Profile</h1><div className="card pf-skel" /><div className="card pf-skel" /></div>

  return (
    <div className="pf">
      <h1>Your Finance Profile</h1>
      <p className="tab-caption">Tell ARIA about yourself once and every answer gets personal. Everything here is optional.</p>

      {error && (
        <div className="ri-error" role="alert">
          Could not load your profile ({error}). <button type="button" className="btn" onClick={() => load(true)}>Try again</button>
        </div>
      )}

      {!error && !hasData && (
        <div className="banner-info">
          <strong>Tell ARIA about yourself once and every answer gets personal.</strong> Start with the quick form below and skip anything you like.
        </div>
      )}

      {hasData && (
        <section aria-label="Dashboard">
          {health ? (
            <div className="ri-hero pf-hero">
              <div className="ri-ring" role="img" aria-label={`Financial health score ${Math.round(health.score)} out of 100`} style={{ '--p': health.score, '--c': tone(health.score) } as React.CSSProperties}>
                <span>{Math.round(health.score)}</span><small>/ 100</small>
              </div>
              <div className="pf-bars">
                <div className="ri-name">Financial health{health.coverage !== undefined && health.coverage < 0.6 && <span className="ri-sub"> · provisional: based on {Math.round(health.coverage * 100)}% of the factors</span>}</div>
                <div className="ri-bars">
                  {health.breakdown.map((b) => (
                    <div key={b.name} className="ri-bar">
                      <span>{b.name}</span>
                      {b.sub == null ? (
                        <span className="ri-sub pf-wide">Add {b.name.toLowerCase()} details to include this.</span>
                      ) : (
                        <>
                          <div className="ri-track" title={b.reason}><div style={{ width: `${Math.round(b.sub * 100)}%`, background: tone(b.sub * 100) }} /></div>
                          <b>{Math.round(b.sub * 100)}</b>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <div className="ri-warn">Your health score is not available right now. Your answers are saved.</div>
          )}

          <div className="ri-grid pf-stats">
            {stats.map(([t, v, hint]) => (
              <div key={t} className="ri-card">
                <div className="ri-sub">{t}</div>
                <div className={v ? 'pf-big' : 'pf-big pf-na'}>{v ?? '-'}</div>
                {!v && <div className="ri-sub">{hint}</div>}
              </div>
            ))}
          </div>

          {!!summary?.goals?.length && (
            <>
              <h3>Goals</h3>
              <ul className="pf-list">
                {summary.goals.map((g) => (
                  <li key={g.name} className="ri-card pf-goal">
                    <div>
                      <strong>{g.name}</strong>
                      <div className="ri-sub">{inr(g.target)} in {g.years} {g.years === 1 ? 'year' : 'years'}{g.sip_needed != null && <> · SIP needed <b>{inr(g.sip_needed)}/month</b></>}</div>
                    </div>
                    {g.on_track != null && (
                      <span className="ri-pill" style={{ background: g.on_track ? 'var(--green)' : 'var(--amber)' }}>{g.on_track ? 'On track' : 'Needs a boost'}</span>
                    )}
                  </li>
                ))}
              </ul>
            </>
          )}

          <h3>What ARIA remembers</h3>
          <ul className="pf-list">
            {Object.entries(sources).map(([k, s]) => {
              const [top, sub] = k.split('.')
              const v = sub ? profile[top]?.[sub] : profile[top]
              if (v == null) return null
              const m = META[k]
              const inline = !sub && !!m?.kind
              return (
                <li key={k} className="pf-mem">
                  <span className="pf-mem-k">{sub ? `${label(top)}: ${label(sub)}` : label(k)}</span>
                  {edit?.k === k ? (
                    <span className="pf-mem-edit">
                      <Inp small label={label(k)} kind={m?.kind} opts={m?.opts} range={m?.range} value={edit.v} onChange={(x) => setEdit({ k, v: x })} />
                      <button type="button" className="btn btn-primary" onClick={saveEdit}>Save</button>
                      <button type="button" className="btn" onClick={() => setEdit(null)}>Cancel</button>
                    </span>
                  ) : (
                    <>
                      <span className="pf-mem-v">{show(k, v)}</span>
                      <span className="ri-pill pf-src" style={{ background: s.src === 'chat' ? 'var(--violet)' : 'var(--accent)' }} title={s.at ? new Date(s.at).toLocaleString() : ''}>{s.src === 'chat' ? 'from chat' : 'from form'}</span>
                      <button type="button" className="btn pf-link" aria-label={`Edit ${label(k)}`} onClick={() => (inline ? setEdit({ k, v }) : jump(stepOf(k)))}>Edit</button>
                      <button type="button" className="btn pf-link pf-del" aria-label={`Forget ${label(k)}`} onClick={() => forget(k)}>Forget</button>
                    </>
                  )}
                </li>
              )
            })}
          </ul>
        </section>
      )}

      {!error && (
        <section aria-label="Quick form" className="card pf-wizard" ref={form}>
          <div className="pf-progress">
            <div>Profile {pct}% complete</div>
            <div className="ri-track" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={pct} aria-label="Profile completeness"><div style={{ width: `${pct}%`, background: 'var(--accent)' }} /></div>
            {missing.length > 0 && (
              <div className="ri-chips">
                Still missing:
                {missing.slice(0, 6).map((m) => <button key={m} type="button" className="ri-chip" onClick={() => jump(stepOf(m))}>{label(m)}</button>)}
                {missing.length > 6 && <span>+{missing.length - 6} more</span>}
              </div>
            )}
          </div>

          <ol className="pf-steps">
            {STEPS.map((s, i) => (
              <li key={s.name}>
                <button type="button" className="pf-step" aria-current={i === step ? 'step' : undefined} onClick={() => jump(i)}>
                  <span className="pf-num">{i + 1}</span><span className="pf-step-name">{s.name}</span>
                </button>
              </li>
            ))}
          </ol>

          <h3 tabIndex={-1} ref={head}>{STEPS[step].name}</h3>
          <p className="tab-caption">{STEPS[step].why} Leave anything blank to skip it.</p>

          {step === 0 && <div className="form-grid">{STEPS[0].keys.map(F)}</div>}
          {step === 1 && (
            <>
              <div className="form-grid">{F('monthly_income')}{F('income_stability')}</div>
              <h4>{label('expenses')}</h4>
              {money('expenses', EXP)}
            </>
          )}
          {step === 2 && money('assets', AST)}
          {step === 3 && (
            <>
              {rows('loans')}
              <div className="form-grid pf-gap">{F('credit_card_outstanding')}{F('term_cover')}{F('health_cover')}</div>
            </>
          )}
          {step === 4 && (
            <>
              {rows('goals')}
              <div className="form-grid pf-gap">{['risk_tolerance', 'horizon_years', 'tax_regime', 'used_80c', 'used_80d'].map(F)}</div>
            </>
          )}

          <div className="pf-nav">
            <button type="button" className="btn" disabled={step === 0} onClick={() => jump(step - 1)}>Back</button>
            <button type="button" className="btn" disabled={step === STEPS.length - 1} onClick={() => jump(step + 1)}>Skip</button>
            <button type="button" className="btn btn-primary" disabled={busy} onClick={saveStep}>{step === STEPS.length - 1 ? 'Save' : 'Save & next'}</button>
          </div>
          <p className="pf-msg" role="status">{msg}</p>
        </section>
      )}

      {!error && (
        <p><button type="button" className="btn pf-danger" onClick={deleteAll}>Delete all my finance data</button></p>
      )}

      <hr className="divider" />
      <h2>Your Transactions</h2>
      <p className="tab-caption">
        Feeds Module 1's LSTM spend forecast and Isolation Forest anomaly detector — both need real transaction history to produce
        anything beyond a zero-signal default. Anomaly detection needs 10+ entries.
      </p>

      <StatementUpload
        onImported={(profileUpdated) => {
          api.getTransactions(owner).then(setTransactions).catch(() => {})
          load(false, profileUpdated)
        }}
      />

      <div className="card txn-form">
        <div className="form-grid">
          <div className="field">
            <label>Date</label>
            <input aria-label="Date" className="input" type="date" value={txnForm.date} onChange={(e) => setTxnForm({ ...txnForm, date: e.target.value })} />
          </div>
          <div className="field">
            <label>Category</label>
            <select aria-label="Category" className="input" value={txnForm.category} onChange={(e) => setTxnForm({ ...txnForm, category: e.target.value })}>
              {CATEGORIES.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
          </div>
          <div className="field">
            <label>Amount (₹)</label>
            <input
              aria-label="Amount (₹)"
              className="input"
              type="number"
              value={txnForm.amount}
              onChange={(e) => setTxnForm({ ...txnForm, amount: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Merchant (optional)</label>
            <input aria-label="Merchant (optional)" className="input" value={txnForm.merchant} onChange={(e) => setTxnForm({ ...txnForm, merchant: e.target.value })} />
          </div>
          <div className="field">
            <label>Channel (optional)</label>
            <select aria-label="Channel (optional)" className="input" value={txnForm.channel} onChange={(e) => setTxnForm({ ...txnForm, channel: e.target.value })}>
              {CHANNELS.map((c) => (
                <option key={c} value={c}>
                  {c || '—'}
                </option>
              ))}
            </select>
          </div>
        </div>
        <button className="btn btn-primary" onClick={addTransaction} type="button" style={{ marginTop: 16 }}>
          Add transaction
        </button>
      </div>

      {transactions.length > 0 ? (
        <>
          <div className="card txn-table-wrap">
            <table className="txn-table">
              <thead>
                <tr>
                  <th>date</th>
                  <th>category</th>
                  <th>amount</th>
                  <th>merchant</th>
                  <th>channel</th>
                </tr>
              </thead>
              <tbody>
                {transactions.map((t) => (
                  <tr key={t.id}>
                    <td>{t.date}</td>
                    <td>{t.category}</td>
                    <td>{t.amount.toLocaleString('en-IN')}</td>
                    <td>{t.merchant ?? ''}</td>
                    <td>{t.channel ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="tab-caption">{transactions.length} transaction(s) on file for this session.</p>
          <button className="btn" onClick={clearAll} type="button">
            Clear all my transactions
          </button>
        </>
      ) : (
        <div className="banner-info">
          No transactions yet — add a few above, or load sample data to try the forecast/anomaly models.
          <div style={{ marginTop: 10 }}>
            <button className="btn" onClick={loadSample} type="button">
              Load sample transactions (demo)
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
