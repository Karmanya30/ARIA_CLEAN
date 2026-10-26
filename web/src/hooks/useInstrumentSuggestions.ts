import { useEffect, useState } from 'react'
import { instrumentPaths } from '../api'
import { useMarket } from './useMarket'
import type { InstrumentSearchResult } from '../types'

/** Hide the previous query's results immediately; useMarket ignores late responses after a path change. */
export function useInstrumentSuggestions(text: string, type = '', market = '') {
  const query = text.trim().replace(/\s+/g, ' ')
  const [term, setTerm] = useState('')
  useEffect(() => {
    const timer = setTimeout(() => setTerm(query), 200)
    return () => clearTimeout(timer)
  }, [query])
  const ready = query.length >= 2 && query === term
  const path = ready ? instrumentPaths.search(term, type) + (market ? `&market=${market}` : '') : null
  const res = useMarket<InstrumentSearchResult>(path, 0)
  return { ...res, items: ready ? res.data?.items ?? [] : [], query, settling: query !== term }
}
