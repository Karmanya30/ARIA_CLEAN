/** TS mirror of the backend /api/markets/* schemas. */
export type OpenStock = (symbol: string) => void

export interface Meta {
  as_of: string
  fetched_at: string
  stale: boolean
  source: string
  delay_min: number
  error?: string
  warming?: boolean
}

export interface OverviewItem {
  symbol: string
  name: string
  group: 'india' | 'global' | 'fx' | 'commodity' | 'crypto'
  price: number
  change: number
  change_pct: number
  prev_close: number
  currency: string
  spark: number[]
}
export interface Overview {
  status: { open: boolean; label: string; now_ist: string; note: string }
  meta: Meta
  items: OverviewItem[]
}

export interface Row {
  symbol: string
  name: string
  sector: string
  price: number
  change_pct: number
  volume: number
  value_cr: number
}
export interface Movers {
  meta: Meta
  gainers: Row[]
  losers: Row[]
  active: Row[]
}

export interface Sectors {
  meta: Meta
  sectors: {
    name: string
    index_symbol: string
    change_pct: number
    value_cr: number
    stocks: { symbol: string; name: string; change_pct: number; value_cr: number }[]
  }[]
}

export interface News {
  meta: Meta
  engine: 'finbert' | 'keywords'
  items: {
    title: string
    source: string
    url: string
    age_hours: number
    sources: number
    tone: 'positive' | 'neutral' | 'negative'
    net: number
    symbols: string[]
  }[]
}

export interface Chart {
  symbol: string
  range: string
  interval: string
  currency: string
  meta: Meta
  bars: { t: number; o: number; h: number; l: number; c: number; v: number }[]
}

export interface Quote {
  symbol: string
  name: string
  price: number
  change_pct: number
  prev_close: number
  day_low: number
  day_high: number
  year_low: number
  year_high: number
  market_cap: number | null
  pe: number | null
  sector: string | null
  volume: number
  meta: Meta
}

export interface SearchHit {
  symbol: string
  name: string
  sector: string
}
