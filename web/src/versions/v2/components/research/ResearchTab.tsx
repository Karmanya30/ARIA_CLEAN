import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { Download, ExternalLink, RefreshCw, Trash2 } from 'lucide-react'
import { api } from '../../api'
import type { ReportMeta, ValidationLatest } from '../../types'
import { CompanySearch } from '../../../../components/research/CompanySearch'
import type { InstrumentSummary } from '../../types'
import './ResearchTab.css'

const DONE = ['ok_beats_baseline', 'no_model_beats_baseline', 'insufficient_evidence', 'data_unavailable', 'failed', 'timeout']
const RUNNING = ['queued', 'computing']

function validationLabel(v: ValidationLatest | null): string {
  if (!v) return ''
  if (RUNNING.includes(v.status)) return `${v.status === 'queued' ? 'Validation queued' : 'Validating forecasts…'}${v.progress ? ` ${v.progress}%` : ''}${v.stage ? ` · ${v.stage}` : ''}`
  if (v.status === 'not_run') return 'Forecast validation not run'
  if (v.status === 'failed' || v.status === 'timeout') return 'Forecast validation failed'
  return 'Forecast validation complete'
}

const RATING_COLOR: Record<string, string> = { BUY: 'var(--green)', HOLD: 'var(--amber)', SELL: 'var(--red)' }

function money(v: number | null): string {
  return v === null ? 'n/a' : `₹${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`
}

/** Saved equity research reports for this device: open one in-app, download it, regenerate it on fresh
 * data (saved as the next version), or delete it. The report itself is the server-rendered HTML document,
 * shown in a script-less sandboxed iframe -- the same document the download contains. */
export function ResearchTab({ onAsk }: { onAsk: (query: string) => void }) {
  const [companyQuery, setCompanyQuery] = useState('')
  const [company, setCompany] = useState<InstrumentSummary | null>(null)
  const [reports, setReports] = useState<ReportMeta[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const [openSyms, setOpenSyms] = useState<Set<string>>(new Set())
  const [kind, setKind] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [validation, setValidation] = useState<ValidationLatest | null>(null)
  const [valError, setValError] = useState<string | null>(null)
  const [frameKey, setFrameKey] = useState(0)
  const lastStatus = useRef<string | undefined>(undefined)

  const load = useCallback(async () => {
    try {
      const list = await api.listReports()
      setReports(list)
      setSelected((cur) => cur ?? list[0]?.id ?? null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load reports')
      setReports([])
    }
  }, [])

  useEffect(() => {
    api
      .listReports()
      .then((list) => {
        setReports(list)
        setSelected((cur) => cur ?? list[0]?.id ?? null)
      })
      .catch((err) => {
        setError(err instanceof Error ? err.message : 'Could not load reports')
        setReports([])
      })
  }, [])

  const selMeta = reports?.find((r) => r.id === selected)
  const valSymbol = selMeta && selMeta.kind !== 'fund_analysis' ? selMeta.symbol : null

  // Fetch the validation state of the open report; while queued/computing poll every 5 s (paused when the tab is hidden).
  useEffect(() => {
    lastStatus.current = undefined
    setValidation(null)
    setValError(null)
    if (!valSymbol) return
    let alive = true
    const poll = () => {
      if (document.hidden) return
      api.validationLatest(valSymbol).then((v) => {
        if (!alive) return
        setValidation(v)
        setValError(null)
        const prev = lastStatus.current
        if (prev && RUNNING.includes(prev) && DONE.includes(v.status)) setFrameKey((k) => k + 1) // the new section is now in the report
        lastStatus.current = v.status
      }).catch(() => alive && setValError('Could not check forecast validation'))
    }
    poll()
    const timer = window.setInterval(() => { const p = lastStatus.current; if (p === undefined || RUNNING.includes(p)) poll() }, 5000)
    document.addEventListener('visibilitychange', poll)
    return () => { alive = false; window.clearInterval(timer); document.removeEventListener('visibilitychange', poll) }
  }, [valSymbol])

  async function startValidation() {
    if (!valSymbol) return
    setValError(null)
    try {
      const out = await api.validationStart(valSymbol)
      lastStatus.current = out.status
      setValidation({ status: out.status, run_id: out.run_id })
    } catch (err) {
      setValError(err instanceof Error ? err.message : 'Could not start validation')
    }
  }

  async function regenerate(id: string) {
    setBusy(id)
    setError(null)
    try {
      const out = await api.regenerateReport(id)
      await load()
      setSelected(out.report_id)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Regeneration failed')
    } finally {
      setBusy(null)
    }
  }

  async function remove(id: string) {
    if (!window.confirm('Delete this saved report version?')) return
    await api.deleteReport(id)
    setSelected(null)
    await load()
  }

  if (reports === null) return <p className="rt-empty">Loading saved reports…</p>

  const isFund = reports.find((r) => r.id === selected)?.kind === 'fund_analysis'
  // newest version of each company first; older versions fold away unless opened or selected
  const firstOf = new Map<string, string>()
  const olderCount: Record<string, number> = {}
  for (const r of reports) {
    const key = `${r.symbol}|${r.kind}`
    if (!firstOf.has(key)) { firstOf.set(key, r.id); olderCount[r.id] = 0 } else olderCount[firstOf.get(key)!]++
  }
  const visible = reports.filter((r) => firstOf.get(`${r.symbol}|${r.kind}`) === r.id || openSyms.has(r.symbol) || r.id === selected)

  return (
    <div className={selected ? 'rt has-selected' : 'rt'}>
      <aside className="rt-list">
        <h1>Research reports</h1>
        <form className="rt-create" aria-label="Create a research report" onSubmit={e => {
          e.preventDefault()
          if (company) onAsk(`equity research report on ${company.symbol}`)
        }}>
          <CompanySearch label="Report company" value={companyQuery}
            onChange={text => { setCompanyQuery(text); setCompany(null) }}
            onPick={item => { setCompany(item); setCompanyQuery(item.name) }} />
          <button type="submit" disabled={!company}>Generate research report</button>
          <p className="rt-hint">Search by partial name or ticker and select a company. Reports support NSE and BSE stocks.</p>
        </form>
        <p className="rt-hint">Ask ARIA for an “equity research report on …”, “DuPont analysis of …” or “mutual fund analysis of …” and it is saved here automatically.</p>
        {error && <p className="rt-error">{error}</p>}
        {reports.length === 0 && <p className="rt-empty">No saved reports yet. Open Chat and ask for one, for example “equity research report on TCS”. It takes under a minute and appears here.</p>}
        {visible.map((r) => (
          <Fragment key={r.id}>
          <div className={r.id === selected ? 'rt-item active' : 'rt-item'}>
            <button type="button" className="rt-open" onClick={() => setSelected(r.id)}>
              <span className="rt-name">
                {r.company} <span className="rt-ver">v{r.version}</span>
              </span>
              <span className="rt-sub">
                {r.created_at?.slice(0, 10)} · {r.symbol}
              </span>
              <span className="rt-row">
                <span className="rt-chip" style={{ background: r.rating ? RATING_COLOR[r.rating] : 'var(--ink-faint)' }}>
                  {r.stance ?? 'Not assessed'}
                </span>
                <span>{money(r.fair_value)}</span>
                {r.status === 'caveated' && <span className="rt-warn">caveated</span>}
              </span>
            </button>
            {r.id === selected && (
              <div className="rt-actions">
                <a href={api.reportHtmlUrl(r.id, kind)} target="_blank" rel="noreferrer" title="Open in a new tab">
                  <ExternalLink size={14} />
                </a>
                <a href={api.reportDownloadUrl(r.id, 'html', kind)} title="Download HTML">
                  <Download size={14} />
                </a>
                <a href={api.reportDownloadUrl(r.id, 'pdf', kind)} title="Download PDF">
                  PDF
                </a>
                <a href={api.reportHtmlUrl(r.id, kind, true)} target="_blank" rel="noreferrer" title="Open print dialog (Save as PDF)">
                  Print
                </a>
                <a href={api.reportDownloadUrl(r.id, 'md')} title="Download Markdown">
                  MD
                </a>
                <a href={api.reportDownloadUrl(r.id, 'json')} title="Download all data (JSON)">
                  JSON
                </a>
                {r.kind !== 'fund_analysis' && (
                  <button type="button" onClick={() => regenerate(r.id)} disabled={busy !== null} title="Regenerate on fresh data (new version)">
                    <RefreshCw size={14} className={busy === r.id ? 'rt-spin' : ''} />
                  </button>
                )}
                <button type="button" onClick={() => remove(r.id)} disabled={busy !== null} title="Delete this version">
                  <Trash2 size={14} />
                </button>
              </div>
            )}
          </div>
          {olderCount[r.id] > 0 && (
            <button type="button" className="rt-more" onClick={() => setOpenSyms((o) => { const n = new Set(o); if (n.has(r.symbol)) n.delete(r.symbol); else n.add(r.symbol); return n })}>
              {openSyms.has(r.symbol) ? 'Hide earlier versions' : `Show ${olderCount[r.id]} earlier version${olderCount[r.id] > 1 ? 's' : ''} of ${r.company}`}
            </button>
          )}
          </Fragment>
        ))}
        {!isFund && (
        <label className="rt-hint">
          Report type{' '}
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">As generated</option>
            <option value="equity_research">Equity research report</option>
            <option value="financial_model">Financial model report</option>
            <option value="valuation">Valuation report</option>
            <option value="dupont">DuPont and ratio analysis</option>
          </select>
        </label>
        )}
        {busy && <p className="rt-hint">Regenerating on fresh data… this takes up to a minute.</p>}
      </aside>
      <section className="rt-viewer">
        {selected ? (
          <>
          <button type="button" className="rt-back" onClick={() => setSelected(null)}>← All reports</button>
          <div className="rt-vbar" aria-live="polite">
            {valSymbol && (
              <>
                <span className={validation && RUNNING.includes(validation.status) ? 'rt-vchip running' : 'rt-vchip'}>{valError ?? validationLabel(validation)}</span>
                {validation?.status === 'not_run' && <button type="button" onClick={startValidation}>Run validation</button>}
                {validation && DONE.includes(validation.status) && <button type="button" onClick={() => setFrameKey((k) => k + 1)}>Refresh</button>}
                {valError && <button type="button" onClick={startValidation}>Retry</button>}
              </>
            )}
          </div>
          <iframe key={`${selected}-${kind}-${frameKey}`} title="Equity research report" src={api.reportHtmlUrl(selected, isFund ? '' : kind)} sandbox="" />
          </>
        ) : (
          <p className="rt-empty">Choose a report from the list to read it here. You can switch its view (equity research, financial model, valuation, DuPont) without regenerating it.</p>
        )}
      </section>
    </div>
  )
}
