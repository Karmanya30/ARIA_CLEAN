import { useState } from 'react'
import { Check, Copy, Download, ExternalLink, ShieldAlert, ShieldCheck } from 'lucide-react'
import { api } from '../../api'
import type { DebateArgument, ReportTable, ResearchReportData } from '../../types'
import { Markdown } from './Markdown'
import { ForYou } from './IntelligenceSummary'
import './ResearchReport.css'

// Mirrors modules/equity_research/intelligence/facts.py fmt(): percentages arrive as percent numbers.
function fmt(v: number | null | undefined, unit: string): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return 'n/a'
  const sign = v < 0 ? '-' : ''
  const a = Math.abs(v)
  const n = (x: number, d: number) => x.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })
  if (unit === '%') return `${sign}${n(a, 1)}%`
  if (unit === 'x') return `${sign}${n(a, 1)}x`
  if (unit === '₹') return `${sign}₹${n(a, 2)}`
  if (unit === '₹ Cr') return `${sign}₹${n(a, a >= 100 ? 0 : 1)} Cr`
  return `${sign}${n(a, 2)}${unit ? ` ${unit}` : ''}`
}

const RATING_COLOR: Record<string, string> = { BUY: 'var(--green)', HOLD: 'var(--amber)', SELL: 'var(--red)' }

function Section({ title, children, open = false }: { title: string; children: React.ReactNode; open?: boolean }) {
  return (
    <details className="rr-section" open={open}>
      <summary>{title}</summary>
      <div className="rr-section-body">{children}</div>
    </details>
  )
}

function FootballField({ methods, price, fair }: { methods: ResearchReportData['valuation']['methods']; price: number | null; fair: number | null }) {
  if (!methods.length) return null
  const points = methods.flatMap((m) => [m.low, m.high]).concat(price ? [price] : [])
  const lo = Math.min(...points)
  const hi = Math.max(...points)
  const pad = (hi - lo) * 0.08 || 1
  const pos = (x: number) => ((x - lo + pad) / (hi - lo + 2 * pad)) * 100
  return (
    <div className="rr-football" role="img" aria-label="Valuation range by method against the current share price">
      {methods.map((m) => (
        <div className="rr-football-row" key={m.key}>
          <span className="rr-football-label">{m.label}</span>
          <div className="rr-football-track">
            <div className="rr-football-bar" style={{ left: `${pos(m.low)}%`, width: `${pos(m.high) - pos(m.low)}%` }} />
            <div className="rr-football-mid" style={{ left: `${pos(m.mid)}%` }} title={`Mid ${fmt(m.mid, '₹')}`} />
            {price ? <div className="rr-football-price" style={{ left: `${pos(price)}%` }} /> : null}
            {fair ? <div className="rr-football-fair" style={{ left: `${pos(fair)}%` }} /> : null}
          </div>
          <span className="rr-football-range">
            {fmt(m.low, '₹')} – {fmt(m.high, '₹')}
          </span>
        </div>
      ))}
      <p className="rr-legend">
        <span className="rr-key rr-key-price" /> share price {fmt(price, '₹')}
        {fair ? (
          <>
            {' '}
            · <span className="rr-key rr-key-fair" /> fair value {fmt(fair, '₹')}
          </>
        ) : null}{' '}
        · bar = low–high case, tick = mid
      </p>
    </div>
  )
}

function DataTable({ table }: { table: ReportTable }) {
  return (
    <div className="rr-table-wrap">
      <p className="rr-table-title">
        {table.title} <span className="rr-muted">· {table.source}</span>
      </p>
      <table className="rr-table">
        <thead>
          <tr>
            <th />
            {table.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((r) => (
            <tr key={r.label}>
              <th>
                {r.label}
                {r.kind === 'calculated' ? <span className="rr-tag" title="calculated by ARIA"> calc</span> : null}
              </th>
              {table.columns.map((c) => (
                <td key={c}>{fmt(r.values[c], r.unit)}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function Side({ title, args, tone }: { title: string; args: DebateArgument[]; tone: 'bull' | 'bear' }) {
  return (
    <div className={`rr-side rr-side-${tone}`}>
      <p className="rr-side-title">{title}</p>
      {args.length === 0 ? <p className="rr-muted">No argument the evidence supports.</p> : null}
      {args.map((a, i) => (
        <div className="rr-arg" key={i}>
          <p>{a.claim}</p>
          <div className="rr-chips">
            {a.evidence.map((e) => (
              <span className="rr-chip" key={e.id} title={`${e.id} · ${e.period}`}>
                {e.label} <b>{e.value}</b>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  )
}

export function ResearchReport({ report, reportId }: { report: ResearchReportData; reportId?: string | null }) {
  const [copied, setCopied] = useState(false)
  const s = report.stance
  const val = report.valuation
  const dcf = val.dcf
  const caveated = report.status === 'caveated'

  async function copy() {
    try {
      await navigator.clipboard.writeText(report.markdown)
      setCopied(true)
      setTimeout(() => setCopied(false), 1800)
    } catch {
      /* clipboard unavailable (insecure context): leave the button as is */
    }
  }

  return (
    <div className="rr">
      <div className="rr-header">
        <div>
          <p className="rr-title">{report.title}</p>
          <p className="rr-sub">
            {report.company.sector ?? ''} {report.company.industry ? `· ${report.company.industry}` : ''} · {report.company.basis} statements · as of {report.company.as_of}
          </p>
        </div>
        <div className="rr-actions">
          {reportId && (
            <>
              <a className="rr-copy" href={api.reportHtmlUrl(reportId)} target="_blank" rel="noreferrer">
                <ExternalLink size={14} /> Open full report{report.meta ? ` (v${report.meta.version})` : ''}
              </a>
              <a className="rr-copy" href={api.reportDownloadUrl(reportId, 'html')}>
                <Download size={14} /> Download
              </a>
            </>
          )}
          <button type="button" className="rr-copy" onClick={copy} aria-label="Copy the full report as markdown">
            {copied ? <Check size={14} /> : <Copy size={14} />} {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>

      <div className="rr-stance">
        {s.rating ? (
          <span className="rr-rating" style={{ background: RATING_COLOR[s.rating] }}>
            {s.stance}
          </span>
        ) : (
          <span className="rr-rating rr-rating-none">Not assessed</span>
        )}
        <div className="rr-stance-figures">
          <span>
            Fair value <b>{s.fair_value !== null ? fmt(s.fair_value, '₹') : `${fmt(s.low, '₹')} – ${fmt(s.high, '₹')}`}</b>
            {s.fair_value === null && s.rating ? <span className="rr-muted"> (point withheld)</span> : null}
          </span>
          <span>
            Price <b>{fmt(s.price, '₹')}</b>
          </span>
          <span>
            Upside <b>{fmt(s.upside_pct, '%')}</b>
          </span>
          <span>
            Confidence <b>{s.confidence ? s.confidence.replace('_', ' ') : 'n/a'}</b>
          </span>
        </div>
        <span className={`rr-status ${caveated ? 'rr-status-warn' : 'rr-status-ok'}`}>
          {caveated ? <ShieldAlert size={13} /> : <ShieldCheck size={13} />} {caveated ? 'Verification: caveated' : 'Verification: passed'}
        </span>
      </div>

      <ForYou data={report.for_you} />

      {s.notes.length > 0 && (
        <ul className="rr-notes">
          {s.notes.map((n, i) => (
            <li key={i}>{n}</li>
          ))}
        </ul>
      )}

      <Section title="Investment thesis" open>
        <ul>
          {report.thesis.map((t, i) => (
            <li key={i}>{t}</li>
          ))}
        </ul>
        <Markdown text={report.business} />
      </Section>

      <Section title="Financial analysis">
        <Markdown text={report.financials.text} />
        {report.financials.tables.map((t) => (
          <DataTable table={t} key={t.title} />
        ))}
      </Section>

      <Section title="Valuation" open>
        <Markdown text={val.text} />
        <FootballField methods={val.methods} price={s.price} fair={s.fair_value} />
        {val.methods.length > 0 && (
          <table className="rr-table">
            <thead>
              <tr>
                <th>Method</th>
                <th>Low</th>
                <th>Mid</th>
                <th>High</th>
                <th>Basis</th>
              </tr>
            </thead>
            <tbody>
              {val.methods.map((m) => (
                <tr key={m.key}>
                  <th>{m.label}</th>
                  <td>{fmt(m.low, '₹')}</td>
                  <td>{fmt(m.mid, '₹')}</td>
                  <td>{fmt(m.high, '₹')}</td>
                  <td className="rr-left">{m.basis}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {dcf?.reverse && dcf.reverse.implied_growth !== null && (
          <p className="rr-callout">
            Reverse DCF: today's price implies about <b>{fmt(dcf.reverse.implied_growth * 100, '%')}</b> annual revenue growth for ten years, against the model's starting growth of{' '}
            <b>{fmt(dcf.inputs.growth[0] * 100, '%')}</b>.
          </p>
        )}
        {dcf?.reverse?.reason === 'above_range' && (
          <p className="rr-callout">No revenue growth up to 50% a year justifies today's price under these assumptions: the market is pricing something a cash-flow model cannot capture.</p>
        )}
        {dcf?.sensitivity && (
          <div className="rr-table-wrap">
            <p className="rr-table-title">DCF value per share: WACC (rows) × terminal growth (columns)</p>
            <table className="rr-table">
              <thead>
                <tr>
                  <th />
                  {dcf.sensitivity.tg_values.map((g) => (
                    <th key={g}>{(g * 100).toFixed(1)}%</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {dcf.sensitivity.prices.map((row, i) => (
                  <tr key={i}>
                    <th>{(dcf.sensitivity!.wacc_values[i] * 100).toFixed(1)}%</th>
                    {row.map((p, j) => (
                      <td key={j} className={i === 2 && j === 2 ? 'rr-base' : ''}>
                        {p === null ? '—' : fmt(p, '₹')}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {val.comps && (
          <div className="rr-table-wrap">
            <p className="rr-table-title">
              Peer multiples <span className="rr-muted">· {val.comps.group} peers; blank = unavailable or excluded from the median</span>
            </p>
            <table className="rr-table">
              <thead>
                <tr>
                  <th>Peer</th>
                  <th>P/E</th>
                  <th>P/B</th>
                  <th>EV/EBITDA</th>
                </tr>
              </thead>
              <tbody>
                {val.comps.peers.map((p) => (
                  <tr key={p.symbol}>
                    <th>{p.name}</th>
                    {(['pe', 'pb', 'ev_ebitda'] as const).map((k) => (
                      <td key={k}>{p[k] === null || p.excluded.includes(k) ? '' : fmt(p[k], 'x')}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <ul className="rr-notes">
          {val.notes.map((n, i) => (
            <li key={`n${i}`}>{n}</li>
          ))}
          {Object.entries(val.skipped).map(([k, why]) => (
            <li key={k}>
              <b>{k}</b> not run: {why}
            </li>
          ))}
        </ul>
      </Section>

      {(report.debate.bull.length > 0 || report.debate.bear.length > 0) && (
        <Section title="Bull vs bear">
          <div className="rr-debate">
            <Side title="Bull case" args={report.debate.bull} tone="bull" />
            <Side title="Bear case" args={report.debate.bear} tone="bear" />
          </div>
          {report.debate.judge && (
            <div className="rr-judge">
              <p>
                <b>Judge: {report.debate.judge.call}</b> · conviction {(report.debate.judge.conviction * 100).toFixed(0)}%
                {report.debate.aligned === false ? <span className="rr-diverge"> · differs from the valuation-implied rating</span> : null}
              </p>
              <p>
                <b>Swing factor:</b> {report.debate.judge.swing_factor}
              </p>
              <p>
                <b>What would change the call:</b> {report.debate.judge.change_my_mind}
              </p>
            </div>
          )}
        </Section>
      )}

      <Section title="Risks">
        <ul className="rr-risks">
          {report.risks.map((r, i) => (
            <li key={i}>
              <span className={`rr-cat rr-sev-${r.severity || 'llm'}`}>{r.category}</span> {r.title ? <b>{r.title}. </b> : null}
              {r.detail}
              {r.origin === 'llm' ? <span className="rr-tag"> AI-interpreted from sources</span> : null}
            </li>
          ))}
        </ul>
      </Section>

      {(report.catalysts.length > 0 || report.news.length > 0) && (
        <Section title="Catalysts and recent news">
          {report.catalysts.length > 0 && (
            <ul>
              {report.catalysts.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          )}
          <ul className="rr-news">
            {report.news.map((n, i) => (
              <li key={i}>
                <span className="rr-muted">
                  N{i + 1} · {n.date}
                </span>{' '}
                {n.title} <span className="rr-muted">({n.source})</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="Assumptions">
        <table className="rr-table">
          <tbody>
            {report.assumptions.map((a) => (
              <tr key={a.id}>
                <th>{a.label}</th>
                <td>{a.text}</td>
                <td className="rr-left rr-muted">{a.method}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Verification and sources" open={caveated}>
        <ul className="rr-checks">
          {report.audit.checks.map((c) => (
            <li key={c.name} className={`rr-check rr-check-${c.status}`}>
              <b>{c.status === 'pass' ? '✓' : c.status === 'info' ? 'ℹ' : '⚠'} {c.title}</b>
              {c.findings.map((f, i) => (
                <span className="rr-finding" key={i}>
                  {f}
                </span>
              ))}
            </li>
          ))}
        </ul>
        <p className="rr-muted">
          Sources: {report.sources.map((s2) => `${s2.source} (${s2.count})`).join(' · ')}
        </p>
      </Section>

      <p className="rr-disclaimer">{report.disclaimer}</p>
    </div>
  )
}
