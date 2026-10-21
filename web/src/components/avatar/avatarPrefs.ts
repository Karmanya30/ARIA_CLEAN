import { useSyncExternalStore } from 'react'

/** off = no avatar speaks; disk = the audio-reactive ARIA disk; live = the local live-face engine (disk if it is unreachable). */
export type AvatarMode = 'off' | 'disk' | 'live'
export const AVATAR_MODES: { id: AvatarMode; label: string; blurb: string }[] = [
  { id: 'off', label: 'Off', blurb: 'No avatar. Replies stay as text.' },
  { id: 'disk', label: 'Disk', blurb: 'The audio-reactive ARIA disk, using ARIA’s own voice.' },
  { id: 'live', label: 'Live face', blurb: 'A lip-synced face generated on this computer. Falls back to the disk if the engine is not running.' },
]

const MODE_KEY = 'aria_avatar_mode'
const REPLICA_KEY = 'aria_avatar_replica'
const LOOK_KEY = 'aria_avatar_look'
const SPEAK_KEY = 'aria_avatar_speak'
const CAPTIONS_KEY = 'aria_avatar_captions'

const listeners = new Set<() => void>()
const read = (key: string): string | null => { try { return localStorage.getItem(key) } catch { return null } }
const memory = new Map<string, string>() // storage blocked: choices last until reload
const get = (key: string) => read(key) ?? memory.get(key) ?? null
const put = (key: string, value: string) => {
  memory.set(key, value)
  try { localStorage.setItem(key, value) } catch { /* kept in memory */ }
  listeners.forEach((l) => l())
}
const subscribe = (l: () => void) => {
  listeners.add(l)
  window.addEventListener('storage', l)
  return () => { listeners.delete(l); window.removeEventListener('storage', l) }
}

export function getAvatarMode(): AvatarMode {
  const v = get(MODE_KEY)
  return v === 'off' || v === 'disk' || v === 'live' ? v : 'live'
}
export const setAvatarMode = (m: AvatarMode) => put(MODE_KEY, m)
export const useAvatarMode = (): [AvatarMode, (m: AvatarMode) => void] => [useSyncExternalStore(subscribe, getAvatarMode), setAvatarMode]

export const getReplicaId = () => get(REPLICA_KEY) || null
export const setReplicaId = (id: string | null) => put(REPLICA_KEY, id ?? '')
export const useReplicaId = (): [string | null, (id: string | null) => void] => [useSyncExternalStore(subscribe, getReplicaId), setReplicaId]

/** How the live face is framed and what is behind it (sent to the engine when the stream opens). */
export interface Look { framing: 'bust' | 'face' | 'full'; bg: string }
export const BACKGROUNDS = [{ id: 'original', label: 'Original' }, { id: 'blur', label: 'Blurred' }, { id: '#0e1621', label: 'Navy' }, { id: '#f4f1ea', label: 'Ivory' }, { id: 'transparent', label: 'Transparent' }]
export const FRAMINGS = [{ id: 'bust', label: 'Bust' }, { id: 'face', label: 'Face' }, { id: 'full', label: 'Full' }] as const
const DEFAULT_LOOK: Look = { framing: 'bust', bg: 'original' }
const looks = new Map<string, Look>()
export function getLook(): Look {
  const raw = get(LOOK_KEY) ?? ''
  let out = looks.get(raw)
  if (!out) {
    try { const o = JSON.parse(raw); out = { framing: FRAMINGS.some((f) => f.id === o.framing) ? o.framing : 'bust', bg: typeof o.bg === 'string' && /^(original|blur|transparent|#[0-9a-f]{6})$/i.test(o.bg) ? o.bg : 'original' } } catch { out = DEFAULT_LOOK }
    looks.set(raw, out)
  }
  return out
}
export const setLook = (l: Look) => put(LOOK_KEY, JSON.stringify(l))
export const useLook = (): [Look, (l: Look) => void] => [useSyncExternalStore(subscribe, getLook), setLook]

/** Panel toggles: speak replies aloud (on by default) and show captions (off by default). */
export const useAvatarToggle = (kind: 'speak' | 'captions'): [boolean, (on: boolean) => void] => {
  const key = kind === 'speak' ? SPEAK_KEY : CAPTIONS_KEY
  const on = useSyncExternalStore(subscribe, () => (get(key) ?? (kind === 'speak' ? 'on' : 'off')) === 'on')
  return [on, (v) => put(key, v ? 'on' : 'off')]
}
