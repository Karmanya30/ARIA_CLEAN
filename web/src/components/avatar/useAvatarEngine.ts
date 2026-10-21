import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AvatarClient, type ClientSnapshot } from './avatarClient'
import { useEngineHealth } from './engineApi'
import type { EngineHealth, EngineMetrics, EngineState, SpeakOptions } from './protocol'

export type EngineStatus = 'connecting' | 'live' | 'unavailable'

export interface AvatarEngine {
  /** What the face is doing: the engine's state, or 'speaking' while buffered audio is still playing. */
  state: EngineState
  /** connecting = first check in progress; live = connected and usable; unavailable = unreachable, or the engine says so. */
  status: EngineStatus
  available: boolean
  reason: string | null
  health: EngineHealth | null
  metrics: EngineMetrics
  caption: string
  hasFrame: boolean
  speak: (text: string, opts?: SpeakOptions) => boolean
  interrupt: () => void
  /** Call from a user gesture so the browser lets the voice play. */
  unlock: () => void
  /** After another tab replaced this session: take it back. */
  reconnect: () => void
  /** Tell the engine the user is talking (attentive pose). */
  listening: (on: boolean) => void
  /** Ref callback for the <canvas> the face is drawn into. */
  attachCanvas: (el: HTMLCanvasElement | null) => void
}

const START: ClientSnapshot = { connection: 'closed', serverState: 'idle', playing: false, hasFrame: false, caption: '', metrics: {} }

/** Connects to the local avatar engine while `enabled`. `replicaId` falls back to the engine's default replica. */
export function useAvatarEngine({ replicaId, enabled = true, framing, bg }: { replicaId?: string | null; enabled?: boolean; framing?: string; bg?: string } = {}): AvatarEngine {
  const { health, error, checked } = useEngineHealth(enabled)
  const replica = replicaId || health?.replica_default || null
  const lookRef = useRef({ framing, bg })
  useEffect(() => { lookRef.current = { framing, bg } }, [framing, bg])
  const replicaRef = useRef(replica)
  useEffect(() => { replicaRef.current = replica }, [replica])
  const [snap, setSnap] = useState<ClientSnapshot>(START)
  const client = useMemo(() => new AvatarClient(() => replicaRef.current, () => lookRef.current, setSnap), [])
  const up = enabled && !!health && health.ready !== false // the engine answers /health while it is still loading
  const attachCanvas = useCallback((el: HTMLCanvasElement | null) => client.setCanvas(el), [client])

  // Connect once the engine answers /health; reconnect when the replica changes.
  useEffect(() => {
    if (!up) return
    client.start()
    return () => { client.stop(); setSnap(START) }
  }, [client, up, replica, framing, bg])

  const live = up && snap.connection === 'open' && snap.serverState !== 'unavailable'
  const status: EngineStatus = live ? 'live' : (!enabled || (checked && !up) || snap.serverState === 'unavailable') ? 'unavailable' : 'connecting'
  return {
    state: !live ? 'unavailable' : snap.playing ? 'speaking' : snap.serverState,
    status,
    available: live,
    reason: !enabled ? null : !up && checked ? (health ? 'The avatar engine is still starting' : error ?? 'The local avatar engine is not running.') : snap.serverState === 'unavailable' ? (snap.reason ?? 'The avatar engine is not ready.') : null,
    health,
    metrics: snap.metrics,
    caption: snap.caption,
    hasFrame: snap.hasFrame,
    speak: client.speak.bind(client),
    interrupt: client.interrupt.bind(client),
    unlock: client.unlock.bind(client),
    reconnect: client.reconnect.bind(client),
    listening: client.listening.bind(client),
    attachCanvas,
  }
}
