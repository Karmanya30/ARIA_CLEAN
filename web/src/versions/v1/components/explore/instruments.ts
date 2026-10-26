import type { InstrumentQuote, InstrumentSummary, InstrumentType } from '../../types'
import { fmtNum } from '../markets/format'

export const TYPE_CHIPS: { id: '' | InstrumentType; label: string; one: string }[] = [
  { id: '', label: 'All', one: 'Instrument' },
  { id: 'stock', label: 'Stocks', one: 'Stock' },
  { id: 'mf', label: 'Mutual funds', one: 'Mutual fund' },
  { id: 'etf', label: 'ETFs', one: 'ETF' },
  { id: 'crypto', label: 'Crypto', one: 'Crypto' },
  { id: 'bond', label: 'Bonds', one: 'Bond' },
  { id: 'index', label: 'Indices', one: 'Index' },
  { id: 'commodity', label: 'Commodities', one: 'Commodity' },
  { id: 'currency', label: 'Currencies', one: 'Currency' },
]
export const typeLabel = (t: string) => TYPE_CHIPS.find((c) => c.id === t)?.one ?? t
export const typeFromId = (id: string) => id.split(':')[0]

/** What the headline number is called for each kind of instrument. */
export const priceLabel = (t: string) =>
  ({ mf: 'NAV', index: 'Level', bond: 'Yield / price', currency: 'Rate', commodity: 'Price' } as Record<string, string>)[t] ?? 'Price'

/** Money with the instrument's own currency; falls back to a plain number if the code is unknown. */
export function fmtMoney(v: number | null | undefined, currency?: string | null, digits = 2): string {
  if (v == null || !Number.isFinite(v)) return '–'
  if (currency && /^[A-Za-z]{3}$/.test(currency)) {
    try {
      return new Intl.NumberFormat(currency.toUpperCase() === 'INR' ? 'en-IN' : 'en-US', {
        style: 'currency',
        currency: currency.toUpperCase(),
        minimumFractionDigits: v !== 0 && Math.abs(v) < 1 ? 4 : digits,
        maximumFractionDigits: v !== 0 && Math.abs(v) < 1 ? 4 : digits,
      }).format(v)
    } catch {
      /* unknown currency code */
    }
  }
  return fmtNum(v, digits) + (currency ? ` ${currency}` : '')
}

// ── Instrument watchlist (all types). Stocks are mirrored into the Markets watchlist (aria_watchlist), which only knows tickers. ──
const WL = 'aria_watchlist_ix'
const MARKETS_WL = 'aria_watchlist'
const readList = (key: string): string[] => {
  try {
    const v = JSON.parse(localStorage.getItem(key) || '[]')
    return Array.isArray(v) ? v.filter((s) => typeof s === 'string') : []
  } catch {
    return []
  }
}
const writeList = (key: string, v: string[]) => {
  try {
    localStorage.setItem(key, JSON.stringify(v))
  } catch {
    /* storage blocked: the star just will not persist */
  }
}
export const readIxWatchlist = () => readList(WL)
export function toggleIxWatch(id: string): boolean {
  const list = readList(WL)
  const on = !list.includes(id)
  writeList(WL, on ? [...list, id] : list.filter((x) => x !== id))
  if (typeFromId(id) === 'stock') {
    const sym = id.slice(id.indexOf(':') + 1)
    const m = readList(MARKETS_WL)
    writeList(MARKETS_WL, on ? (m.includes(sym) ? m : [...m, sym]) : m.filter((x) => x !== sym))
  }
  window.dispatchEvent(new Event('aria-watchlist'))
  return on
}

/** Starter questions per kind, so the Ask box is never a blank page. */
export function suggestionsFor(q: Pick<InstrumentQuote | InstrumentSummary, 'type' | 'name'>): string[] {
  const n = q.name
  const base = [`What is ${n} in simple words?`, `What are the main risks of ${n}?`]
  const more: Record<string, string[]> = {
    stock: [`Is ${n} expensive compared with its peers?`, `What moved ${n} recently?`],
    mf: [`What does ${n} invest in?`, `Is a SIP in ${n} a sensible way to start?`],
    etf: [`What does ${n} track and what does it cost?`, `How is an ETF different from an index fund?`],
    crypto: [`Why is ${n} so volatile?`, `What are the tax rules for ${n} in India?`],
    bond: [`How do interest rates affect ${n}?`, `What does this yield tell me?`],
    index: [`What is inside ${n}?`, `How can I invest in ${n}?`],
    commodity: [`What drives the price of ${n}?`, `How can an Indian investor hold ${n}?`],
    currency: [`What moves ${n}?`, `How does ${n} affect my investments?`],
  }
  return [...base, ...(more[q.type] ?? [])]
}
