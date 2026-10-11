import { useEffect, useId, useRef, useState } from 'react'
import { Plus, X } from 'lucide-react'
import { useMarket } from '../../hooks/useMarket'
import { Delta } from './Delta'
import { fmtNum } from './format'
import { DataProv } from './Provenance'
import type { OpenStock, Quote, SearchHit } from './types'

const KEY = 'aria_watchlist'
const SEED = ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'INFY.NS']
const short = (s: string) => s.replace(/\.(NS|BO)$/, '')
const qpath = (s: string) => `/api/markets/quote?symbol=${encodeURIComponent(s)}`

function load(): string[] {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) ?? 'null')
    if (Array.isArray(v) && v.every((x) => typeof x === 'string')) return v
  } catch { /* storage blocked or corrupt: fall back to the seed */ }
  return SEED
}

function Row({ symbol, onOpen, onRemove }: { symbol: string; onOpen: OpenStock; onRemove: () => void }) {
  const q = useMarket<Quote>(qpath(symbol), 60_000)
  const d = q.data
  return (
    <li className="mk-wl-row">
      <button type="button" className="mk-link" onClick={() => onOpen(symbol)}>
        <b>{short(symbol)}</b><span className="mk-faint">{d?.name ?? (q.error ? 'Quote unavailable' : '')}</span>
      </button>
      {d ? <><span className="num">{fmtNum(d.price)}</span><Delta value={d.change_pct} /></> : <span className="mk-skel mk-wl-skel" aria-hidden="true" />}
      <button type="button" className="mk-x" onClick={onRemove} aria-label={`Remove ${short(symbol)} from watchlist`}><X size={14} aria-hidden="true" /></button>
    </li>
  )
}

export function Watchlist({ onOpen }: { onOpen: OpenStock }) {
  const [list, setList] = useState(load)
  const [text, setText] = useState('')
  const [term, setTerm] = useState('')
  const [hi, setHi] = useState(0)
  const [open, setOpen] = useState(false)
  const id = useId()
  const inp = useRef<HTMLInputElement>(null)
  const first = useMarket<Quote>(list[0] ? qpath(list[0]) : null, 60_000)
  useEffect(() => { // the stock drawer's star writes storage and fires this event
    const sync = () => setList(load())
    window.addEventListener('aria-watchlist', sync); window.addEventListener('storage', sync)
    return () => { window.removeEventListener('aria-watchlist', sync); window.removeEventListener('storage', sync) }
  }, [])
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(list)) } catch { /* ignore */ } }, [list])
  useEffect(() => { const t = setTimeout(() => setTerm(text.trim()), 250); return () => clearTimeout(t) }, [text])
  const s = useMarket<SearchHit[]>(term.length >= 2 ? `/api/markets/search?q=${encodeURIComponent(term)}` : null, 600_000)
  const hits = (s.data ?? []).filter((h) => !list.includes(h.symbol)).slice(0, 6)
  const showList = open && term.length >= 2
  const add = (sym: string) => { setList((l) => (l.includes(sym) ? l : [...l, sym])); setText(''); setTerm(''); setOpen(false) }
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); setOpen(true); setHi((h) => Math.max(0, Math.min(h + 1, hits.length - 1))) }
    else if (e.key === 'ArrowUp') { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)) }
    else if (e.key === 'Enter' && showList && hits[hi]) { e.preventDefault(); add(hits[hi].symbol) }
    else if (e.key === 'Escape') setOpen(false)
  }
  return (
    <section className="mk-card mk-panel mk-watch" aria-label="Watchlist" style={{ minHeight: 300 }}>
      <header className="mk-panel-h"><h2>Watchlist</h2></header>
      <div className="mk-combo">
        <label htmlFor={`${id}-in`} className="sr-only">Add a stock to your watchlist</label>
        <Plus size={16} aria-hidden="true" className="mk-combo-ic" />
        <input ref={inp} id={`${id}-in`} className="mk-input" role="combobox" aria-expanded={showList} aria-controls={`${id}-lb`} aria-autocomplete="list" aria-activedescendant={showList && hits[hi] ? `${id}-o${hi}` : undefined}
          placeholder="Add a stock, e.g. Reliance" autoComplete="off" value={text} onChange={(e) => { setText(e.target.value); setOpen(true); setHi(0) }} onKeyDown={onKey} onBlur={() => setOpen(false)} />
        {showList && (
          <ul id={`${id}-lb`} role="listbox" className="mk-listbox" aria-label="Search results">
            {hits.map((h, i) => (
              <li key={h.symbol} id={`${id}-o${i}`} role="option" aria-selected={i === hi} onMouseDown={(e) => { e.preventDefault(); add(h.symbol) }}>
                <b>{short(h.symbol)}</b> <span className="mk-faint">{h.name}</span>
              </li>
            ))}
            {!hits.length && <li className="mk-faint" role="presentation">{s.loading ? 'Searching…' : 'No matches'}</li>}
          </ul>
        )}
      </div>
      {list.length ? (
        <ul className="mk-wl">{list.map((sym) => <Row key={sym} symbol={sym} onOpen={onOpen} onRemove={() => { setList((l) => l.filter((x) => x !== sym)); inp.current?.focus() }} />)}</ul>
      ) : <p className="mk-empty">Your watchlist is empty. Search above to add a stock.</p>}
      <footer className="mk-panel-f">{first.data && <DataProv meta={first.data.meta} />}</footer>
    </section>
  )
}
