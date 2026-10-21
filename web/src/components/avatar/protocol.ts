/** Wire protocol of the local avatar engine (port 8010, proxied by Vite at /avatar-engine). */

export type Framing = 'bust' | 'face' | 'full'
export type Background = 'original' | 'blur' | 'transparent' | string // or '#rrggbb'
export type EngineState = 'idle' | 'thinking' | 'speaking' | 'listening' | 'unavailable'

export interface EngineHealth { status: string; ready?: boolean; detail?: string; session_active?: boolean; voices?: string[]; backend?: string; gpu?: string; vram_used_mb?: number; fps?: number; replica_default?: string | null }
export interface Replica { replica_id: string; name: string; preview_url?: string }
export interface EngineMetrics { ttfb_ms?: number; fps?: number; gen_ms?: number }
export interface SpeakOptions { voice?: string; emotion?: string; style?: { rate?: number } }

export type ServerEvent =
  | { type: 'audio_format'; sample_rate: number }
  | { type: 'state'; value: EngineState; reason?: string }
  | { type: 'caption'; text: string; t_start: number; t_end: number }
  | ({ type: 'metrics' } & EngineMetrics)
  | { type: 'pong' }
  | { type: 'error'; message?: string }

export const MEDIA_VIDEO = 0x01
export const MEDIA_AUDIO = 0x02
export const HEADER_BYTES = 9 // 1 type byte, uint32 sequence, uint32 timestamp (ms)

export interface MediaMessage { kind: 'video' | 'audio'; seq: number; ts: number; payload: Uint8Array }

/** The brief says "uint32" without naming the byte order; avatar_engine/protocol.py uses little-endian, which is the default here.
 * Big-endian is switched on only when the first non-zero header reads far smaller that way (sequence and timestamp are small). */
export class MediaParser {
  private little: boolean | null = null

  parse(buf: ArrayBuffer): MediaMessage | null {
    if (buf.byteLength <= HEADER_BYTES) return null
    const view = new DataView(buf)
    const type = view.getUint8(0)
    if (type !== MEDIA_VIDEO && type !== MEDIA_AUDIO) return null
    if (this.little === null) {
      const big = Math.max(view.getUint32(1, false), view.getUint32(5, false))
      const lil = Math.max(view.getUint32(1, true), view.getUint32(5, true))
      if (big !== lil) this.little = lil <= big // undecided while both read the same (all zeros)
    }
    const le = this.little !== false
    return {
      kind: type === MEDIA_VIDEO ? 'video' : 'audio',
      seq: view.getUint32(1, le),
      ts: view.getUint32(5, le),
      payload: new Uint8Array(buf, HEADER_BYTES),
    }
  }
}

/** 16-bit little-endian PCM mono -> floats in [-1, 1]. */
export function pcm16ToFloat(payload: Uint8Array): Float32Array {
  const n = payload.byteLength >> 1
  const view = new DataView(payload.buffer, payload.byteOffset, n * 2)
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) out[i] = view.getInt16(i * 2, true) / 32768
  return out
}
