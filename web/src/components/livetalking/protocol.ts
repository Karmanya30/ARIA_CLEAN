/** Pure helpers for talking to the LiveTalking service (upstream API: JSON {code,msg,data}, offer -> {sdp,type,sessionid}). No DOM or React, so node can test them. */

export const OFFER_TIMEOUT_MS = 5000
export const NOT_RUNNING = 'LiveTalking service is not running: start the Lip-sync GPU launcher'

export type OfferResult =
  | { ok: true; sdp: string; type: RTCSdpType; sessionid: string }
  | { ok: false; kind: 'busy' | 'error'; reason: string }

/** Turns the /offer HTTP status and JSON body into an answer or a reason. code:-1 is how upstream says "no free session" and also any server error. */
export function parseOffer(status: number, body: unknown): OfferResult {
  const b = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>
  if (status >= 200 && status < 300 && typeof b.sdp === 'string' && b.sdp && b.sessionid != null) {
    return { ok: true, sdp: b.sdp, type: (b.type as RTCSdpType) || 'answer', sessionid: String(b.sessionid) }
  }
  const msg = typeof b.msg === 'string' ? b.msg : ''
  if (b.code === -1) return { ok: false, kind: /max|busy|session|full/i.test(msg) ? 'busy' : 'error', reason: msg || 'busy' }
  return { ok: false, kind: 'error', reason: msg || `HTTP ${status}` }
}

/** Waits before retry n (0-based): 2 s, 4 s, 8 s ... capped at 30 s. */
export const backoffMs = (attempt: number) => Math.min(30000, 2000 * 2 ** Math.max(0, attempt))

/** SSE payloads are JSON eventpoints like {"status":"start","text":"..."}. */
export function speakingFromEvent(data: string): boolean | null {
  try {
    const s = (JSON.parse(data) as { status?: string }).status
    return s === 'start' ? true : s === 'end' ? false : null
  } catch { return null }
}

/** The /is_speaking reply: {code:0, data:true|false}. */
export const speakingFromPoll = (body: unknown): boolean | null => {
  const b = body as { code?: number; data?: unknown } | null
  return b && b.code === 0 && typeof b.data === 'boolean' ? b.data : null
}
