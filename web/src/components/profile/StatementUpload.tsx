import { useRef, useState } from 'react'
import { api } from '../../api'
import { AskChips } from './SpendingInsights'
import type { StatementImportResult, StatementPreview } from '../../types'

const ACCEPT = '.csv,.tsv,.txt,.xlsx,.xlsm,.xls,.pdf,.json,.ofx,.qif,*/*'
const inr = (n: number) => `₹${Math.round(n).toLocaleString('en-IN')}`
const label = (k: string) => k.replace(/_/g, ' ')
const mon = (d: string) => new Date(d).toLocaleDateString('en-IN', { month: 'short', year: 'numeric' })

/** Upload a bank/card statement, preview what was read, then import it. Files are parsed server-side and not stored. */
export function StatementUpload({ onImported, onAsk }: { onImported: (profileUpdated: boolean) => void; onAsk?: (q: string) => void }) {
  const input = useRef<HTMLInputElement>(null)
  const [state, setState] = useState<'idle' | 'reading' | 'preview' | 'importing'>('idle')
  const [drag, setDrag] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState<StatementImportResult | null>(null)
  const [pv, setPv] = useState<StatementPreview | null>(null)
  const [applyProfile, setApplyProfile] = useState(false)

  async function read(file: File | undefined) {
    if (!file) return
    setError(''); setDone(null); setState('reading')
    try {
      const r = await api.parseStatement(file)
      setPv(r)
      setApplyProfile(Object.keys(r.suggested_profile?.expenses ?? {}).length > 0 || r.suggested_profile?.monthly_income != null)
      setState('preview')
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'We could not read that file.')
      setState('idle')
    }
  }

  async function doImport() {
    if (!pv) return
    setState('importing'); setError('')
    try {
      const r = await api.importStatement(pv.import_id, applyProfile)
      setDone(r); setPv(null); setState('idle')
      onImported(r.profile_updated)
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'The import failed. Please try again.')
      setState('preview')
    }
  }

  function reset() { setPv(null); setError(''); setState('idle'); if (input.current) input.current.value = '' }

  const busy = state === 'reading' || state === 'importing'
  const cats = pv ? Object.entries(pv.summary.monthly_avg).sort((a, b) => b[1] - a[1]) : []
  const top = cats[0]?.[1] || 1

  return (
    <div className="card su" aria-busy={busy}>
      <h3>Upload a statement</h3>
      {state !== 'preview' && state !== 'importing' && (
        <div
          className={`su-drop${drag ? ' su-drag' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); read(e.dataTransfer.files[0]) }}
        >
          <p>Upload a bank or card statement (PDF, Excel, CSV or any text export). We read it on this device's session only; the file itself isn't stored.</p>
          <p className="su-or">Drag a file here, or</p>
          <input ref={input} id="su-file" className="sr-only" type="file" accept={ACCEPT} onChange={(e) => read(e.target.files?.[0])} disabled={busy} />
          <label htmlFor="su-file" className="btn btn-primary su-pick">Choose file</label>
        </div>
      )}
      <div role="status" aria-live="polite">
        {state === 'reading' && <p>Reading your statement…</p>}
        {state === 'importing' && <p>Importing…</p>}
        {done && (
          <div className="banner-info">
            Imported {done.imported} transaction(s); {done.duplicates} duplicate(s) skipped.
            {done.profile_updated ? ' Your profile spending was updated.' : ''}
            <AskChips onAsk={onAsk} />
          </div>
        )}
      </div>
      {error && (
        <div className="banner-info" role="alert">
          {error}{' '}
          <button type="button" className="btn" onClick={reset}>Try another file</button>
        </div>
      )}
      {pv && (
        <div className="su-preview">
          <p><strong>{pv.filename}</strong> ({pv.format}) · {mon(pv.period.from)}–{mon(pv.period.to)}, {pv.period.months} month(s)</p>
          <p>{pv.rows_total} transaction(s) read, {pv.skipped} skipped. {pv.importable !== undefined && `${pv.importable} will be saved as spending (income and investments are summarised below, not stored).`}</p>
          {pv.warnings.length > 0 && <div className="banner-info"><ul>{pv.warnings.map((w) => <li key={w}>{w}</li>)}</ul></div>}
          <div className="txn-table-wrap">
            <table className="txn-table">
              <caption className="sr-only">First {Math.min(10, pv.rows.length)} transactions read</caption>
              <thead><tr><th>date</th><th>merchant</th><th>category</th><th>amount</th></tr></thead>
              <tbody>
                {pv.rows.slice(0, 10).map((r, i) => (
                  <tr key={i}>
                    <td>{r.date}</td><td>{r.merchant}</td><td>{r.category}</td>
                    <td>{r.direction === 'credit' ? '+' : '-'}{r.amount.toLocaleString('en-IN')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cats.length > 0 && (
            <>
              <h4>Spending per month, by category</h4>
              <div className="ri-bars">
                {cats.map(([k, v]) => (
                  <div key={k} className="ri-bar">
                    <span>{label(k)}</span>
                    <div className="ri-track"><div style={{ width: `${Math.round((v / top) * 100)}%`, background: 'var(--accent)' }} /></div>
                    <b>{inr(v)}</b>
                  </div>
                ))}
              </div>
            </>
          )}
          <ul className="su-lines">
            <li>Average monthly income: {inr(pv.summary.avg_monthly_income)}</li>
            <li>EMIs paid: {inr(pv.summary.emi_total)} · Investments: {inr(pv.summary.investment_total)}</li>
          </ul>
          <label className="su-opt">
            <input type="checkbox" checked={applyProfile} onChange={(e) => setApplyProfile(e.target.checked)} />
            <span>
              Also update my profile with these monthly averages
              <small>This replaces the spending breakdown currently on file.</small>
            </span>
          </label>
          <div className="su-actions">
            <button type="button" className="btn btn-primary" onClick={doImport} disabled={busy || (pv.importable ?? pv.rows_total) === 0}>Import {pv.importable ?? pv.rows_total} transactions</button>
            <button type="button" className="btn" onClick={reset} disabled={busy}>Cancel</button>
          </div>
        </div>
      )}
    </div>
  )
}
