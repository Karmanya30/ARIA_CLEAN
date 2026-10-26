import { useState } from 'react'
import { Pause, Play } from 'lucide-react'
import { useMarket } from '../../hooks/useMarket'
import { Delta } from './Delta'
import { fmtIst, fmtNum } from './format'
import type { Movers, OpenStock, Overview } from './types'

const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Fixed strip under the top bar: indices first, then top movers; each item opens that stock. */
export function TickerTape({ onOpen }: { onOpen: OpenStock }) {
  const ov = useMarket<Overview>('/api/markets/overview', 30_000)
  const mv = useMarket<Movers>('/api/markets/movers', 30_000)
  const [paused, setPaused] = useState(false)
  const motion = paused || reduced() ? 'off' : 'on'

  const items = [
    ...(ov.data?.items.filter((i) => i.group === 'india') ?? []),
    ...[...(mv.data?.gainers.slice(0, 5) ?? []), ...(mv.data?.losers.slice(0, 5) ?? [])],
  ].map((i) => ({ symbol: i.symbol, name: i.name, price: i.price, pct: i.change_pct }))
  const asOf = ov.data?.meta.as_of ?? mv.data?.meta.as_of

  const list = (hidden: boolean) => (
    <ul className="tape-list" aria-hidden={hidden || undefined}>
      {items.map((i) => (
        <li key={i.symbol}>
          <button type="button" className="tape-item" tabIndex={hidden ? -1 : undefined} onClick={() => onOpen(i.symbol)} title={i.name}>
            <b>{i.symbol.replace(/\.(NS|BO)$/, '')}</b>
            <span className="num">{fmtNum(i.price)}</span>
            <Delta value={i.pct} />
          </button>
        </li>
      ))}
    </ul>
  )

  return (
    <div className="tape" data-motion={motion} role="region" aria-label="Market ticker">
      {items.length > 0 ? (
        <>
          <div className="tape-track">
            {list(false)}
            {list(true)}
          </div>
          <button type="button" className="tape-toggle" aria-pressed={paused} onClick={() => setPaused((p) => !p)}>
            {paused ? <Play size={12} aria-hidden="true" /> : <Pause size={12} aria-hidden="true" />}
            {paused ? 'Play' : 'Pause'}
          </button>
        </>
      ) : ov.error && mv.error ? (
        <span className="tape-note">Market data unavailable{asOf ? ` · last updated ${fmtIst(asOf)}` : ''}</span>
      ) : (
        <span className="mk-skel tape-skel" style={{ ['--h' as string]: '12px' }} aria-label="Loading market data" role="status" />
      )}
    </div>
  )
}
