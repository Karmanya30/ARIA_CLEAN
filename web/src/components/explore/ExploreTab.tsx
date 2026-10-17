import { useEffect, useState } from 'react'
import { Compass, X } from 'lucide-react'
import { instrumentPaths } from '../../api'
import { useMarket } from '../../hooks/useMarket'
import type { InstrumentQuote } from '../../types'
import { Delta } from '../markets/Delta'
import { InstrumentSearch } from './InstrumentSearch'
import { fmtMoney, readIxWatchlist, toggleIxWatch } from './instruments'
import './explore.css'

function WatchRow({ id, onOpen }: { id: string; onOpen: (id: string) => void }) {
  const q = useMarket<InstrumentQuote>(instrumentPaths.quote(id), 60_000)
  const d = q.data
  return (
    <li className="ix-wrow">
      <button type="button" className="ix-wmain" onClick={() => onOpen(id)}>
        <b>{d?.name ?? id.slice(id.indexOf(':') + 1)}</b>
        {d ? <span className="num">{fmtMoney(d.price, d.currency)}</span> : <span className="mk-skel ix-wskel" aria-hidden="true" />}
        {d?.change_pct != null && <Delta value={d.change_pct} />}
      </button>
      <button type="button" className="mk-x" aria-label={`Remove ${d?.name ?? id} from watchlist`} onClick={() => toggleIxWatch(id)}>
        <X size={14} aria-hidden="true" />
      </button>
    </li>
  )
}

export function ExploreTab({ onOpenInstrument }: { onOpenInstrument: (id: string) => void }) {
  const [wl, setWl] = useState(readIxWatchlist)
  useEffect(() => {
    const sync = () => setWl(readIxWatchlist())
    window.addEventListener('aria-watchlist', sync)
    window.addEventListener('storage', sync)
    return () => (window.removeEventListener('aria-watchlist', sync), window.removeEventListener('storage', sync))
  }, [])

  return (
    <section className="ix-page">
      <header className="ix-head">
        <h1>
          <Compass size={26} aria-hidden="true" /> Explore
        </h1>
        <p className="mk-sub">Find any stock, mutual fund, ETF, coin, bond, index, commodity or currency. Open it to see its price, history and risks, test a SIP, and ask ARIA about it.</p>
      </header>

      <div className="mk-card ix-searchcard">
        <InstrumentSearch onPick={(it) => onOpenInstrument(it.id)} />
      </div>

      {wl.length > 0 && (
        <section className="mk-card" aria-label="Your watchlist">
          <h2 className="ix-h2">Your watchlist</h2>
          <ul className="ix-wl">{wl.map((id) => <WatchRow key={id} id={id} onOpen={onOpenInstrument} />)}</ul>
        </section>
      )}


    </section>
  )
}
