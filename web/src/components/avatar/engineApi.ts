import { useEffect, useState } from 'react'
import type { EngineHealth, Replica } from './protocol'

/** Vite proxies /avatar-engine/* to the local engine on port 8010 (prefix stripped). */
export const ENGINE_BASE = '/avatar-engine'

async function fail(res: Response): Promise<never> {
  const raw = await res.text().catch(() => '')
  let msg = ''
  try { const d = JSON.parse(raw)?.detail; msg = typeof d === 'string' ? d : '' } catch { /* plain text */ }
  throw new Error(msg || (res.status === 502 || res.status === 503 || res.status === 504
    ? 'The local avatar engine is not running.' : raw.slice(0, 160) || `Engine error ${res.status}`))
}

export const engineApi = {
  health: async (signal?: AbortSignal): Promise<EngineHealth> => {
    const res = await fetch(`${ENGINE_BASE}/health`, { signal, cache: 'no-store' })
    if (!res.ok) await fail(res)
    const body = await res.json()
    if (!body || typeof body !== 'object' || typeof body.status !== 'string') throw new Error('Unexpected reply from the avatar engine.')
    return body as EngineHealth
  },
  replicas: async (): Promise<Replica[]> => {
    const res = await fetch(`${ENGINE_BASE}/replicas`, { cache: 'no-store' })
    if (!res.ok) await fail(res)
    const list = await res.json()
    return Array.isArray(list) ? (list as Replica[]) : []
  },
  /** Multipart upload with progress (fetch cannot report upload progress). */
  createReplica: (file: File, name: string | undefined, onProgress: (fraction: number) => void): Promise<{ replica_id: string }> =>
    new Promise((resolve, reject) => {
      const form = new FormData()
      form.append('file', file)
      form.append('image', file) // the contract says "multipart image or short video": send under both common field names
      if (name) form.append('name', name)
      const xhr = new XMLHttpRequest()
      xhr.open('POST', `${ENGINE_BASE}/replicas`)
      xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(e.loaded / e.total) }
      xhr.onerror = () => reject(new Error('Could not reach the avatar engine. Is it running?'))
      xhr.ontimeout = () => reject(new Error('The upload timed out.'))
      xhr.timeout = 180_000
      xhr.onload = () => {
        let body: { replica_id?: string; detail?: unknown } = {}
        try { body = JSON.parse(xhr.responseText) } catch { /* not JSON */ }
        if (xhr.status >= 200 && xhr.status < 300 && body.replica_id) resolve({ replica_id: body.replica_id })
        else reject(new Error(typeof body.detail === 'string' ? body.detail
          : xhr.status === 413 ? 'That file is too large.' : xhr.status === 415 || xhr.status === 422 ? 'The engine could not use that file. Try a clear front-facing photo or a short video.'
          : xhr.status >= 502 ? 'The local avatar engine is not running.' : `Upload failed (${xhr.status}).`))
      }
      xhr.send(form)
    }),
  deleteReplica: async (id: string) => {
    const res = await fetch(`${ENGINE_BASE}/replicas/${encodeURIComponent(id)}`, { method: 'DELETE' })
    if (!res.ok) await fail(res)
  },
  previewUrl: (r: Replica) => r.preview_url ? (r.preview_url.startsWith('/') ? ENGINE_BASE + r.preview_url : r.preview_url) : `${ENGINE_BASE}/replicas/${encodeURIComponent(r.replica_id)}/preview`,
  /** takeover=1: a page reload or a remount replaces the old session instead of being refused as busy. */
  streamUrl: (replicaId: string | null | undefined, look: { framing?: string; bg?: string } = {}) => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const q = new URLSearchParams({ takeover: '1' })
    if (replicaId) q.set('replica_id', replicaId)
    if (look.framing) q.set('framing', look.framing)
    if (look.bg && look.bg !== 'original') q.set('bg', look.bg)
    return `${proto}://${window.location.host}${ENGINE_BASE}/stream?${q}`
  },
}

export interface HealthState { health: EngineHealth | null; error: string | null; checked: boolean; rttMs: number | null }

/** Polls /health: quickly while the engine is down (so Settings and the chat notice it start), slowly once it is up. */
export function useEngineHealth(enabled = true, upEveryMs = 8000, downEveryMs = 3000): HealthState {
  const [state, setState] = useState<HealthState>({ health: null, error: null, checked: false, rttMs: null })
  useEffect(() => {
    if (!enabled) return
    let timer = 0
    let stopped = false
    let controller = new AbortController()
    let misses = 0
    let wasUp = false
    const tick = async () => {
      let next: HealthState
      controller = new AbortController()
      const timeout = window.setTimeout(() => controller.abort(), 4000)
      const t0 = performance.now()
      try {
        next = { health: await engineApi.health(controller.signal), error: null, checked: true, rttMs: Math.round(performance.now() - t0) }
      } catch (e) {
        next = { health: null, error: e instanceof Error && e.name !== 'AbortError' ? e.message : 'The local avatar engine is not running.', checked: true, rttMs: null }
      }
      clearTimeout(timeout)
      if (stopped) return
      // A busy engine can miss one check while it renders: only the second miss in a row counts as down.
      misses = next.health ? 0 : misses + 1
      if (next.health || misses >= 2 || !wasUp) setState(next)
      wasUp = !!next.health
      timer = window.setTimeout(tick, next.health ? upEveryMs : misses === 1 ? 1000 : downEveryMs)
    }
    void tick()
    return () => { stopped = true; clearTimeout(timer); controller.abort() }
  }, [enabled, upEveryMs, downEveryMs])
  return state
}
