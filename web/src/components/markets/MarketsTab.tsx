import './MarketsTab.css'
import { useState } from 'react'
import { Sparkles } from 'lucide-react'
import { useMarket } from '../../hooks/useMarket'
import { IndexCard } from './IndexCard'
import { MarketStatusBar } from './MarketStatusBar'
import { MoversTable } from './MoversTable'
import { NewsFeed } from './NewsFeed'
import { PersonalPanel } from './PersonalPanel'
import { Provenance } from './Provenance'
import { SectorHeatmap } from './SectorHeatmap'
import { StockDrawer } from './StockDrawer'
import { Watchlist } from './Watchlist'
import type { Movers, News, OpenStock, Overview, OverviewItem, Sectors } from './types'

const GROUPS = [['india', 'India'], ['global', 'Global'], ['fx', 'Currency'], ['commodity', 'Commodities'], ['crypto', 'Crypto']] as const
const ASKS = ['Why is the market moving today?', 'Which sectors are strongest?', 'What should I watch this week?']

const greeting = () => {
  const h = Number(new Date().toLocaleString('en-GB', { timeZone: 'Asia/Kolkata', hour: '2-digit', hour12: false }))
  return h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening'
}

/** One deterministic sentence from live numbers; only uses parts that loaded. */
function insight(ov: Overview | null, mv: Movers | null, sc: Sectors | null) {
  const parts: string[] = []
  const nifty = ov?.items.find((i) => i.symbol === '^NSEI')
  if (nifty) parts.push(`${nifty.name} is ${nifty.change_pct >= 0 ? 'up' : 'down'} ${Math.abs(nifty.change_pct).toFixed(1)}%`)
  if (sc && sc.sectors.length > 1) {
    const s = [...sc.sectors].sort((a, b) => b.change_pct - a.change_pct)
    parts.push(`${s[0].name} leads, ${s[s.length - 1].name} lags`)
  }
  const b = mv && breadth(mv)
  if (b) parts.push(`${b.up} of ${b.total} tracked stocks advancing`)
  return parts.join('; ')
}

/** Advancers vs decliners across every distinct stock the movers feed returned. */
function breadth(mv: Movers) {
  const all = new Map([...mv.gainers, ...mv.losers, ...mv.active].map((r) => [r.symbol, r.change_pct]))
  const up = [...all.values()].filter((p) => p > 0).length
  return all.size ? { up, down: [...all.values()].filter((p) => p < 0).length, total: all.size } : null
}

export function MarketsTab({ onAsk, onOpenStock, selectedSymbol }: { onAsk: (q: string) => void; onOpenStock?: OpenStock; selectedSymbol?: string | null }) {
  const ov = useMarket<Overview>('/api/markets/overview', 30_000)
  const mv = useMarket<Movers>('/api/markets/movers', 30_000)
  const sc = useMarket<Sectors>('/api/markets/sectors', 60_000)
  const nw = useMarket<News>('/api/markets/news', 120_000)
  const [group, setGroup] = useState<OverviewItem['group']>('india')
  const [symbol, setSymbol] = useState<string | null>(selectedSymbol ?? null)
  // App's ticker tape opens a stock by passing selectedSymbol; the drawer here shows it.
  const [seen, setSeen] = useState(selectedSymbol)
  if (selectedSymbol !== seen) { setSeen(selectedSymbol); if (selectedSymbol) setSymbol(selectedSymbol) }
  const open: OpenStock = (s) => { setSymbol(s); onOpenStock?.(s) }
  const close = () => { setSymbol(null); onOpenStock?.('') } // clear App's selection so the same tape stock can reopen

  const items = ov.data?.items ?? []
  const shown = items.filter((i) => i.group === group)
  const text = insight(ov.data, mv.data, sc.data)
  const b = mv.data && breadth(mv.data)

  return (
    <section className="mk-page">
      <header className="mk-head">
        <div>
          <h1>Markets</h1>
          <p className="mk-sub">{greeting()}. Here is how the market looks right now.</p>
        </div>
        <MarketStatusBar ov={ov.data} error={ov.error} />
      </header>

      <div className="mk-pills mk-groups" role="group" aria-label="Index group">
        {GROUPS.map(([id, l]) => <button key={id} type="button" className="mk-pillbtn" aria-pressed={group === id} onClick={() => setGroup(id)}>{l}</button>)}
      </div>
      <div className="mk-indices" role="list" aria-label="Indices and benchmarks">
        {ov.data
          ? shown.map((i) => <div role="listitem" key={i.symbol}><IndexCard item={i} onOpen={open} /></div>)
          : [0, 1, 2, 3].map((i) => <div key={i} className="mk-card mk-index" aria-hidden="true">{ov.error ? (i === 0 ? <span className="mk-empty">Indices are unavailable right now.</span> : null) : <span className="mk-skel" style={{ ['--h' as string]: '100%' }} />}</div>)}
        {ov.data && !shown.length && <p className="mk-empty">No data for this group yet.</p>}
      </div>

      <div className="mk-grid">
        <section className="mk-card mk-insight mk-span-12" aria-label="ARIA insight of the moment">
          <h2><Sparkles size={16} aria-hidden="true" /> ARIA insight of the moment</h2>
          <p className="mk-insight-t">{text ? `${text}.` : 'Insight will appear when market data loads.'}</p>
          {b && (
            <div className="mk-breadth">
              <div className="mk-breadth-bar" role="img" aria-label={`${b.up} advancing, ${b.down} declining, ${b.total - b.up - b.down} unchanged`}>
                <i className="up" style={{ flexGrow: b.up }} /><i className="flat" style={{ flexGrow: b.total - b.up - b.down }} /><i className="down" style={{ flexGrow: b.down }} />
              </div>
              <span className="num"><span className="mk-up">▲ {b.up} advancing</span> · <span className="mk-down">▼ {b.down} declining</span></span>
            </div>
          )}
          <div className="mk-chips">
            {ASKS.map((q) => <button key={q} type="button" className="mk-chip mk-chipbtn" onClick={() => onAsk(q)}>{q}</button>)}
            <Provenance kind="calc" />
          </div>
        </section>

        <div className="mk-span-7"><MoversTable res={mv} onOpen={open} /></div>
        <div className="mk-span-5"><SectorHeatmap res={sc} onOpen={open} /></div>
        <div className="mk-span-7"><NewsFeed res={nw} onOpen={open} onAsk={onAsk} /></div>
        <div className="mk-span-5 mk-stack">
          <Watchlist onOpen={open} />
          <PersonalPanel onAsk={onAsk} />
        </div>
      </div>

      <StockDrawer symbol={symbol} onClose={close} onAsk={onAsk} />
    </section>
  )
}
