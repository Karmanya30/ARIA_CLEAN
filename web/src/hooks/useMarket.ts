import { useEffect, useState } from 'react'

const BASE = '' // same origin as api.ts
const cache = new Map<string, unknown>()
const inflight = new Map<string, Promise<unknown>>()

function load(path: string): Promise<unknown> {
  let p = inflight.get(path)
  if (!p) {
    p = fetch(BASE + path)
      .then((r) => {
        if (!r.ok) throw new Error(r.status === 404 || r.status === 503 ? 'unavailable' : `HTTP ${r.status}`)
        return r.json()
      })
      .then((d) => (cache.set(path, d), d))
      .finally(() => inflight.delete(path))
    inflight.set(path, p)
  }
  return p
}

/** Stale-while-revalidate market data: cached value first, then refreshed every intervalMs (paused while the tab is hidden).
 * Requests are shared per path and not aborted individually (another component may be awaiting the same one); results of
 * an unmounted/changed path are simply ignored. */
export function useMarket<T>(path: string | null, intervalMs: number): { data: T | null; error: string | null; loading: boolean; stale: boolean } {
  const [, tick] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [stale, setStale] = useState(false)
  const data = path ? ((cache.get(path) as T | undefined) ?? null) : null

  useEffect(() => {
    if (!path) return
    let live = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const run = () => {
      if (document.hidden) return
      load(path).then(
        () => live && (setError(null), setStale(false), tick((n) => n + 1)),
        (e: Error) => live && (setError(e.message), setStale(cache.has(path))),
      ).finally(() => {
        if (live) timer = setTimeout(run, intervalMs)
      })
    }
    const onVis = () => {
      if (!document.hidden) {
        clearTimeout(timer)
        run()
      }
    }
    run()
    document.addEventListener('visibilitychange', onVis)
    return () => {
      live = false
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [path, intervalMs])

  return { data, error, loading: !!path && data === null && error === null, stale }
}
