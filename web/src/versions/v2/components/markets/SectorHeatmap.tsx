import { useState } from 'react'
import { Delta } from './Delta'
import { fmtCr, fmtPct } from './format'
import { Panel, type Res } from './Panel'
import type { OpenStock, Sectors } from './types'

/** Tint by |change|: 3% caps at 45% colour so the dark ink keeps >= 4.5:1. */
// --tile-base / --tile-k let Night mode mix into the dark surface at a lower strength (light: white, full strength).
const fill = (p: number) => `color-mix(in srgb, var(${p >= 0 ? '--up' : '--down'}) calc(${Math.round((Math.min(Math.abs(p), 3) / 3) * 45)}% * var(--tile-k, 1)), var(--tile-base, white))`
const arrow = (p: number) => (p > 0 ? '▲' : p < 0 ? '▼' : '–')

type Sector = Sectors['sectors'][number]
const basis = (s: Sector) => (s.basis === 'constituents' ? `avg of ${s.stocks.length} stocks` : 'index')
const tip = (s: Sector) => `${s.name}: ${s.basis === 'constituents' ? `average of its ${s.stocks.length} Nifty 50 stocks (no Yahoo index)` : `${s.index_symbol ?? 'sector'} index`}`

export function SectorHeatmap({ res, onOpen }: { res: Res<Sectors>; onOpen: OpenStock }) {
  const [open, setOpen] = useState<string | null>(null)
  return (
    <Panel title="Sectors" res={res} minH={520} className="mk-sectors">
      {(d) => {
        const sel = d.sectors.find((s) => s.name === open)
        return (
          <>
            <div className="mk-heat">
              {d.sectors.map((s) => (
                <button key={s.name} type="button" className="mk-tile" aria-expanded={open === s.name} title={tip(s)} style={{ flexGrow: Math.max(s.value_cr, 1), background: fill(s.change_pct) }} onClick={() => setOpen(open === s.name ? null : s.name)}>
                  <b>{s.name}</b>
                  <span className="num">{arrow(s.change_pct)} {fmtPct(s.change_pct)}</span>
                  <small className="mk-basis">{basis(s)}</small>
                </button>
              ))}
            </div>
            {sel && !sel.stocks.length && <p className="mk-note">Index only: none of the Nifty 50 are in this sector.</p>}
            {sel && sel.stocks.length > 0 && (
              <div className="mk-chips" role="group" aria-label={`${sel.name} stocks`}>
                {sel.stocks.map((s) => (
                  <button key={s.symbol} type="button" className="mk-chip mk-chipbtn" onClick={() => onOpen(s.symbol)}>
                    {s.symbol.replace(/\.(NS|BO)$/, '')} <Delta value={s.change_pct} />
                  </button>
                ))}
              </div>
            )}
            <details className="mk-details">
              <summary>View as table</summary>
              <div className="mk-scroll">
                <table className="mk-table">
                  <thead><tr><th scope="col">Sector</th><th scope="col" className="r">Change</th><th scope="col">Basis</th><th scope="col" className="r">Traded</th></tr></thead>
                  <tbody>{d.sectors.map((s) => <tr key={s.name}><th scope="row">{s.name}</th><td className="r"><Delta value={s.change_pct} /></td><td title={tip(s)}>{basis(s)}</td><td className="r num">{fmtCr(s.value_cr)}</td></tr>)}</tbody>
                </table>
              </div>
            </details>
          </>
        )
      }}
    </Panel>
  )
}
