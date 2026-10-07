import { useEffect, useState } from 'react'
import { api } from '../../api'

const DONE_KEY = 'aria_onboarding_done'
const GOALS = ['House', 'Retirement', 'Child education', 'Wealth building', 'Emergency fund', 'Other']
const RISKS = [
  ['Conservative', 'I would rather protect my money than chase returns.'],
  ['Moderate', 'I accept some ups and downs for steadier growth.'],
  ['Aggressive', 'I can stay calm through big drops for higher long-run growth.'],
]
const markDone = () => { try { localStorage.setItem(DONE_KEY, '1') } catch { /* storage blocked: shows again next visit */ } }
const isDone = () => { try { return !!localStorage.getItem(DONE_KEY) } catch { return false } }
// "₹1,20,000", "50k", "1.5 lakh" -> number; blank or unreadable -> undefined
function parseMoney(s: string): number | undefined {
  const t = s.toLowerCase().replace(/[₹,\s]/g, '')
  const m = t.match(/^(\d*\.?\d+)(k|l|lac|lakh|cr|crore)?$/)
  if (!m) return undefined
  const mult: Record<string, number> = { k: 1e3, l: 1e5, lac: 1e5, lakh: 1e5, cr: 1e7, crore: 1e7 }
  const n = parseFloat(m[1]) * (mult[m[2]] ?? 1)
  return n > 0 ? n : undefined
}

/** First-run, skippable 3-step setup shown on the chat hero while the profile is empty. */
export function Onboarding({ onSaved, onAsk }: { onSaved: () => void; onAsk: (q: string) => void }) {
  const [show, setShow] = useState(false)
  const [step, setStep] = useState(0)
  const [income, setIncome] = useState('')
  const [goal, setGoal] = useState(GOALS[0])
  const [years, setYears] = useState('')
  const [target, setTarget] = useState('')
  const [risk, setRisk] = useState('Moderate')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (isDone()) return
    let live = true
    api.getProfile().then((p) => { if (live && p.completeness.pct === 0) setShow(true) }).catch(() => {})
    return () => { live = false }
  }, [])

  if (!show) return null
  const skip = () => { markDone(); setShow(false) }
  const inc = parseMoney(income)
  const yrs = Number(years) > 0 ? Number(years) : undefined
  const amt = parseMoney(target)

  async function finish(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    setErr('')
    try {
      await api.saveProfile({
        monthly_income: inc, risk_tolerance: risk, horizon_years: yrs,
        goals: amt && yrs ? [{ name: goal, target: amt, years: yrs }] : undefined,
      })
      markDone()
      onSaved()
      setStep(3)
    } catch {
      setErr('We could not save that just now. Please try again, or skip for now.')
    } finally {
      setBusy(false)
    }
  }

  const g = goal.toLowerCase()
  const asks = [
    inc ? 'How much of my income should I save each month?' : 'How do I decide how much to save each month?',
    `How should I plan for ${g === 'other' ? 'my main goal' : g === 'wealth building' ? 'building wealth' : `my ${g}`}?`,
    'Is my emergency fund enough?',
  ]
  const nav = (primary: string, back?: boolean) => (
    <div className="onb-actions">
      <button type="submit" className="btn btn-primary" disabled={busy}>{busy ? 'Saving…' : primary}</button>
      {back && <button type="button" className="btn" onClick={() => setStep(step - 1)}>Back</button>}
      <button type="button" className="btn" onClick={skip}>Skip</button>
      <span className="onb-dots">Step {step + 1} of 3</span>
    </div>
  )
  const next = (e: React.FormEvent) => { e.preventDefault(); setStep(step + 1) }

  return (
    <section className="onb" aria-labelledby="onb-title">
      <h3 id="onb-title">Make ARIA personal in 3 quick steps</h3>
      <p className="ri-sub">Optional. You can change any of this later in your profile.</p>
      {step === 0 && (
        <form onSubmit={next}>
          <label htmlFor="onb-income">What is your monthly income (₹, after tax)?</label>
          <input id="onb-income" className="input" inputMode="decimal" autoComplete="off" placeholder="e.g. 80,000 or 80k" value={income} onChange={(e) => setIncome(e.target.value)} autoFocus />
          {income && !inc && <p className="ri-sub" role="status">Try a plain number, like 80000 or 80k.</p>}
          {nav('Next')}
        </form>
      )}
      {step === 1 && (
        <form onSubmit={next}>
          <fieldset>
            <legend>What is your main money goal?</legend>
            {GOALS.map((x, n) => (
              <label key={x} className="onb-opt"><input type="radio" name="onb-goal" checked={goal === x} onChange={() => setGoal(x)} autoFocus={n === 0} /> {x}</label>
            ))}
          </fieldset>
          <label htmlFor="onb-years">In how many years?</label>
          <input id="onb-years" className="input" type="number" min="1" max="60" value={years} onChange={(e) => setYears(e.target.value)} />
          <label htmlFor="onb-target">Target amount in ₹ (optional)</label>
          <input id="onb-target" className="input" inputMode="decimal" autoComplete="off" placeholder="e.g. 50 lakh" value={target} onChange={(e) => setTarget(e.target.value)} />
          {nav('Next', true)}
        </form>
      )}
      {step === 2 && (
        <form onSubmit={finish}>
          <fieldset>
            <legend>How comfortable are you with risk?</legend>
            {RISKS.map(([r, d], n) => (
              <label key={r} className="onb-opt"><input type="radio" name="onb-risk" checked={risk === r} onChange={() => setRisk(r)} autoFocus={n === 0} /><span>{r}<small>{d}</small></span></label>
            ))}
          </fieldset>
          {err && <p className="ri-error" role="alert">{err}</p>}
          {nav('Finish', true)}
        </form>
      )}
      {step === 3 && (
        <form onSubmit={(e) => { e.preventDefault(); setShow(false) }}>
          <p role="status">All set. Here are three things you could ask first.</p>
          <div className="onb-asks">
            {asks.map((a, n) => <button key={a} type="button" className="bubble-retry" autoFocus={n === 0} onClick={() => { setShow(false); onAsk(a) }}>{a}</button>)}
          </div>
          <div className="onb-actions"><button type="submit" className="btn">Close</button></div>
        </form>
      )}
    </section>
  )
}
