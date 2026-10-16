import { useEffect, useState } from 'react'
import { ChevronLeft, ChevronRight, Compass, X } from 'lucide-react'
import { instrumentPaths } from '../../api'
import { useMarket } from '../../hooks/useMarket'
import type { InstrumentBrowseResult, InstrumentQuote, InstrumentSummary } from '../../types'
import { Delta } from '../markets/Delta'
import { fmtNum } from '../markets/format'
import { InstrumentSearch, TypeChips } from './InstrumentSearch'
import { fmtMoney, readIxWatchlist, toggleIxWatch, typeLabel } from './instruments'
import './explore.css'

const SORTS = [
  ['name', 'Name (A to Z)'],
  ['change_desc', 'Biggest gainers'],
  ['change_asc', 'Biggest fallers'],
] as const
const PAGE = 20

function Row({ it, onOpen }: { it: InstrumentSummary; onOpen: (id: string) => void }) {
  const hasPrice = typeof it.price === 'number' && Number.isFinite(it.price)
  return (
    <li>
      <button type="button" className="ix-row" onClick={() => onOpen(it.id)}>
        <span className="ix-row-main">
          <b>{it.name}</b>
          <span className="ix-opt-sub">{[it.symbol, it.exchange, it.subtitle].filter(Boolean).join(' · ')}</span>
        </span>
        <span className="ix-tag">{typeLabel(it.type)}</span>
        <span className="ix-row-px num">
          {hasPrice ? fmtMoney(it.price, it.currency) : <span className="ix-dash" aria-label="No price shown in the list">–</span>}
          {typeof it.change_pct === 'number' && <Delta value={it.change_pct} />}
        </span>
      </button>
    </li>
  )
}

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
  const [type, setType] = useState('stock')
  const [filter, setFilter] = useState('')
  const [q, setQ] = useState('')
  const [sort, setSort] = useState<(typeof SORTS)[number][0]>('name')
  const [page, setPage] = useState(1)
  const [wl, setWl] = useState(readIxWatchlist)
  useEffect(() => {
    const t = setTimeout(() => { setQ(filter.trim()); setPage(1) }, 300)
    return () => clearTimeout(t)
  }, [filter])
  useEffect(() => {
    const sync = () => setWl(readIxWatchlist())
    window.addEventListener('aria-watchlist', sync)
    window.addEventListener('storage', sync)
    return () => (window.removeEventListener('aria-watchlist', sync), window.removeEventListener('storage', sync))
  }, [])

  const res = useMarket<InstrumentBrowseResult>(instrumentPaths.browse({ type, q, sort, page, pageSize: PAGE }), 120_000)
  const d = res.data
  const total = d?.meta.total ?? 0
  const pages = Math.max(1, Math.ceil(total / (d?.meta.page_size || PAGE)))
  const label = type ? typeLabel(type).toLowerCase() : 'instrument'

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

      <section className="mk-card ix-browse" aria-label="Browse by category" aria-busy={res.loading}>
        <h2 className="ix-h2">Browse by category</h2>
        <TypeChips value={type} all label="Category" onChange={(t) => { setType(t); setPage(1) }} />
        <div className="ix-tools">
          <div className="ix-fld">
            <label htmlFor="ix-filter">Filter this list</label>
            <input id="ix-filter" className="ix-in" type="search" placeholder={`Name or symbol, e.g. ${type === 'mf' ? 'Flexi cap' : type === 'crypto' ? 'ETH' : 'bank'}`} value={filter} onChange={(e) => setFilter(e.target.value)} autoComplete="off" />
          </div>
          <div className="ix-fld">
            <label htmlFor="ix-sort">Sort by</label>
            <select id="ix-sort" className="ix-in" value={sort} onChange={(e) => { setSort(e.target.value as typeof sort); setPage(1) }}>
              {SORTS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
          </div>
        </div>

        {d ? (
          d.items.length ? (
            <ul className="ix-rows" aria-label={`${typeLabel(type)} list`}>
              {d.items.map((it) => <Row key={it.id} it={it} onOpen={onOpenInstrument} />)}
            </ul>
          ) : (
            <div className="ix-emptybox" role="status">
              <b>{q ? `Nothing in ${label}s matches “${q}”.` : `No ${label}s to show yet.`}</b>
              <p>{d.meta.note || (q ? 'Try a shorter name, the ticker, or clear the filter.' : 'This category may still be loading. Try again in a moment, or search for something specific above.')}</p>
              {q && <button type="button" className="btn" onClick={() => setFilter('')}>Clear the filter</button>}
            </div>
          )
        ) : res.error ? (
          <div className="ix-emptybox" role="status">
            <b>This list is unavailable right now.</b>
            <p>ARIA could not reach its data service. Search above still works for anything it can find; otherwise try again shortly.</p>
          </div>
        ) : (
          <div className="ix-skels" role="status" aria-label="Loading the list">
            {Array.from({ length: 6 }, (_, i) => <span key={i} className="mk-skel" style={{ ['--h' as string]: '56px' }} />)}
          </div>
        )}
        {d && d.items.length > 0 && d.meta.note && <p className="ix-note">{d.meta.note}</p>}

        {d && total > 0 && (
          <nav className="ix-pager" aria-label="Pages">
            <button type="button" className="btn" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>
              <ChevronLeft size={16} aria-hidden="true" /> Previous
            </button>
            <span className="num" aria-live="polite">
              {fmtNum((page - 1) * d.meta.page_size + 1, 0)}–{fmtNum(Math.min(page * d.meta.page_size, total), 0)} of {fmtNum(total, 0)}
            </span>
            <button type="button" className="btn" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>
              Next <ChevronRight size={16} aria-hidden="true" />
            </button>
          </nav>
        )}
      </section>
    </section>
  )
}
