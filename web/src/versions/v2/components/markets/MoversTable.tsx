import { useState } from 'react'
import { Delta } from './Delta'
import { fmtCr, fmtNum } from './format'
import { Panel, type Res } from './Panel'
import type { Movers, OpenStock } from './types'

const TABS = [['gainers', 'Top gainers'], ['losers', 'Top losers'], ['active', 'Most active']] as const

export function MoversTable({ res, onOpen }: { res: Res<Movers>; onOpen: OpenStock }) {
  const [tab, setTab] = useState<(typeof TABS)[number][0]>('gainers')
  return (
    <Panel title="Movers" res={res} minH={520} className="mk-movers" aside={
      <div className="mk-pills" role="group" aria-label="Movers view">
        {TABS.map(([id, l]) => <button key={id} type="button" className="mk-pillbtn" aria-pressed={tab === id} onClick={() => setTab(id)}>{l}</button>)}
      </div>
    }>
      {(d) => {
        const rows = d[tab].slice(0, 10)
        const max = Math.max(...rows.map((r) => Math.abs(r.change_pct)), 0.01)
        return (
          <div className="mk-scroll">
            <table className="mk-table">
              <caption className="sr-only">{TABS.find((t) => t[0] === tab)?.[1]}</caption>
              <thead><tr><th scope="col">Stock</th><th scope="col" className="r">Price</th><th scope="col" className="r">Change</th><th scope="col" className="r mk-hide-sm">{tab === 'active' ? 'Traded' : 'Volume'}</th></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.symbol} onClick={() => onOpen(r.symbol)}>
                    <th scope="row">
                      <button type="button" className="mk-link" onClick={(e) => { e.stopPropagation(); onOpen(r.symbol) }}>
                        <b>{r.symbol.replace(/\.(NS|BO)$/, '')}</b><span className="mk-faint">{r.name}</span>
                      </button>
                    </th>
                    <td className="r num">{fmtNum(r.price)}</td>
                    <td className="r">
                      <Delta value={r.change_pct} />
                      <span className="mk-bar" aria-hidden="true"><i className={r.change_pct >= 0 ? 'up' : 'down'} style={{ width: `${(Math.abs(r.change_pct) / max) * 100}%` }} /></span>
                    </td>
                    <td className="r num mk-hide-sm">{tab === 'active' ? fmtCr(r.value_cr) : fmtNum(r.volume, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      }}
    </Panel>
  )
}
