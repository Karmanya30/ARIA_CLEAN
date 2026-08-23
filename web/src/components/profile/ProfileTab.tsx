import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { FinancialProfile, Transaction } from '../../types'
import { ShapExplainer } from '../chat/ShapExplainer'
import './ProfileTab.css'

const CATEGORIES = ['housing', 'food', 'transport', 'utilities', 'emi', 'entertainment', 'medical', 'other']
const CHANNELS = ['', 'upi', 'card', 'cash', 'netbanking']

const emptyForm = {
  monthly_income: 0,
  age: 30,
  dependents: 0,
  existing_emi: 0,
  emergency_fund_months: 0,
  city_tier: 1,
  tax_regime: 'new',
}

export function ProfileTab({ sessionId }: { sessionId: string }) {
  const [profile, setProfile] = useState<FinancialProfile | null>(null)
  const [form, setForm] = useState(emptyForm)
  const [saved, setSaved] = useState(false)
  const [transactions, setTransactions] = useState<Transaction[]>([])
  const [txnForm, setTxnForm] = useState({
    date: new Date().toISOString().slice(0, 10),
    category: 'housing',
    amount: 0,
    merchant: '',
    channel: '',
  })

  function refresh() {
    api.getProfile(sessionId).then((p) => {
      setProfile(p)
      if (p) {
        setForm({
          monthly_income: p.monthly_income,
          age: p.age,
          dependents: p.dependents,
          existing_emi: p.existing_emi,
          emergency_fund_months: p.emergency_fund_months,
          city_tier: p.city_tier,
          tax_regime: p.tax_regime,
        })
      }
    })
    api.getTransactions(sessionId).then(setTransactions)
  }

  useEffect(refresh, [sessionId])

  async function saveProfile() {
    await api.saveProfile(sessionId, form)
    setSaved(true)
    setTimeout(() => setSaved(false), 2500)
    refresh()
  }

  async function addTransaction() {
    if (txnForm.amount <= 0) return
    await api.addTransaction(sessionId, {
      date: txnForm.date,
      category: txnForm.category,
      amount: txnForm.amount,
      merchant: txnForm.merchant || null,
      channel: txnForm.channel || null,
    })
    setTxnForm((f) => ({ ...f, amount: 0, merchant: '' }))
    refresh()
  }

  async function loadSample() {
    await api.loadSampleTransactions(sessionId)
    refresh()
  }

  async function clearAll() {
    await api.clearTransactions(sessionId)
    refresh()
  }

  return (
    <div>
      <h2>Your Financial Profile</h2>
      <p className="tab-caption">Powers Module 1's risk profile, budget, and SIP recommendations.</p>

      <div className="card profile-form">
        <div className="form-grid">
          <div className="field">
            <label>Monthly income (₹)</label>
            <input
              className="input"
              type="number"
              value={form.monthly_income}
              onChange={(e) => setForm({ ...form, monthly_income: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Existing EMI (₹/month)</label>
            <input
              className="input"
              type="number"
              value={form.existing_emi}
              onChange={(e) => setForm({ ...form, existing_emi: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Age</label>
            <input className="input" type="number" value={form.age} onChange={(e) => setForm({ ...form, age: Number(e.target.value) })} />
          </div>
          <div className="field">
            <label>Emergency fund (months of expenses covered)</label>
            <input
              className="input"
              type="number"
              value={form.emergency_fund_months}
              onChange={(e) => setForm({ ...form, emergency_fund_months: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Dependents</label>
            <input
              className="input"
              type="number"
              value={form.dependents}
              onChange={(e) => setForm({ ...form, dependents: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Tax regime</label>
            <select className="input" value={form.tax_regime} onChange={(e) => setForm({ ...form, tax_regime: e.target.value })}>
              <option value="new">new</option>
              <option value="old">old</option>
            </select>
          </div>
          <div className="field">
            <label>City tier</label>
            <select className="input" value={form.city_tier} onChange={(e) => setForm({ ...form, city_tier: Number(e.target.value) })}>
              <option value={1}>1</option>
              <option value={2}>2</option>
              <option value={3}>3</option>
            </select>
          </div>
        </div>
        <button className="btn btn-primary" onClick={saveProfile} type="button" style={{ marginTop: 16 }}>
          Save profile
        </button>
        {saved && <span className="save-confirm">Profile saved. Ask ARIA a finance question in the Chat tab to see it applied.</span>}
      </div>

      {profile?.risk_label && (
        <>
          <hr className="divider" />
          <div className="card risk-card">
            <div className="mono-label">Current risk profile</div>
            <div className="risk-value">{profile.risk_label}</div>
            <div className="risk-confidence">↑ {Math.round((profile.risk_confidence ?? 0) * 100)}% confidence</div>
          </div>
          {profile.risk_top_features?.length > 0 && (
            <ShapExplainer label={profile.risk_label} topFeatures={profile.risk_top_features} />
          )}
        </>
      )}

      <hr className="divider" />
      <h2>Your Transactions</h2>
      <p className="tab-caption">
        Feeds Module 1's LSTM spend forecast and Isolation Forest anomaly detector — both need real transaction history to produce
        anything beyond a zero-signal default. Anomaly detection needs 10+ entries.
      </p>

      <div className="card txn-form">
        <div className="form-grid">
          <div className="field">
            <label>Date</label>
            <input className="input" type="date" value={txnForm.date} onChange={(e) => setTxnForm({ ...txnForm, date: e.target.value })} />
          </div>
          <div className="field">
            <label>Category</label>
            <select className="input" value={txnForm.category} onChange={(e) => setTxnForm({ ...txnForm, category: e.target.value })}>
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
              className="input"
              type="number"
              value={txnForm.amount}
              onChange={(e) => setTxnForm({ ...txnForm, amount: Number(e.target.value) })}
            />
          </div>
          <div className="field">
            <label>Merchant (optional)</label>
            <input className="input" value={txnForm.merchant} onChange={(e) => setTxnForm({ ...txnForm, merchant: e.target.value })} />
          </div>
          <div className="field">
            <label>Channel (optional)</label>
            <select className="input" value={txnForm.channel} onChange={(e) => setTxnForm({ ...txnForm, channel: e.target.value })}>
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
