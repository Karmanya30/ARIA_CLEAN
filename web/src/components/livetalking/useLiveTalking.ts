import { useCallback, useEffect, useRef, useState } from 'react'
import { NOT_RUNNING, OFFER_TIMEOUT_MS, backoffMs, parseOffer, speakingFromEvent, speakingFromPoll } from './protocol'

const BASE = '/livetalking' // vite proxy -> LiveTalking service (port 8020), prefix stripped
export type LiveTalkingStatus = 'connecting' | 'ready' | 'unavailable'

export interface LiveTalking {
  status: LiveTalkingStatus
  reason: string | null
  speaking: boolean
  hasFrame: boolean
  /** The browser blocked autoplay with sound: show a "click to enable sound" button. */
  soundBlocked: boolean
  enableSound: () => void
  /** Speak this text now (replaces anything being said). */
  speak: (text: string) => void
  interrupt: () => void
  attachVideo: (el: HTMLVideoElement | null) => void
}

const post = (path: string, body: unknown, signal?: AbortSignal) =>
  fetch(BASE + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal })

/** One WebRTC session with the local LiveTalking service while `enabled`. Retries with backoff when the service is down or busy;
 * closes the peer connection on unmount. */
export function useLiveTalking(enabled = true): LiveTalking {
  const [status, setStatus] = useState<LiveTalkingStatus>('connecting')
  const [reason, setReason] = useState<string | null>(null)
  const [speaking, setSpeaking] = useState(false)
  const [hasFrame, setHasFrame] = useState(false)
  const [soundBlocked, setSoundBlocked] = useState(false)
  const sid = useRef<string | null>(null)
  const video = useRef<HTMLVideoElement | null>(null)
  const stream = useRef<MediaStream | null>(null)

  const play = useCallback(() => {
    const v = video.current
    if (!v || !stream.current) return
    if (v.srcObject !== stream.current) v.srcObject = stream.current
    v.muted = false
    v.play().then(() => setSoundBlocked(false), () => { // autoplay with sound blocked: play silently until the user clicks
      v.muted = true
      v.play().catch(() => {})
      setSoundBlocked(true)
    })
  }, [])
  const attachVideo = useCallback((el: HTMLVideoElement | null) => { video.current = el; if (el) play() }, [play])
  const enableSound = useCallback(() => { const v = video.current; if (v) { v.muted = false; void v.play().catch(() => {}); setSoundBlocked(false) } }, [])

  useEffect(() => {
    if (!enabled) return
    let dead = false
    let pc: RTCPeerConnection | null = null
    let timer = 0
    let attempt = 0
    let es: EventSource | null = null
    let poll = 0
    let sseOpen = false
    let talking = false
    const setTalking = (s: boolean) => { talking = s; setSpeaking(s) }

    const teardown = () => {
      es?.close(); es = null; sseOpen = false
      window.clearInterval(poll)
      try { pc?.close() } catch { /* already closed */ }
      pc = null; sid.current = null; stream.current = null
      setTalking(false); setHasFrame(false)
    }
    const fail = (why: string) => {
      if (dead) return
      teardown()
      setStatus('unavailable'); setReason(why)
      timer = window.setTimeout(() => void connect(), backoffMs(attempt++))
    }
    const connect = async () => {
      if (dead) return
      setStatus((s) => (s === 'ready' ? s : 'connecting'))
      const mine = new RTCPeerConnection()
      pc = mine
      const ctl = new AbortController()
      let timeout = 0 // starts once the local offer is ready: browser start-up (first createOffer ~2 s in headless Edge) is not the service's fault
      const stale = () => dead || pc !== mine
      try {
        mine.addTransceiver('video', { direction: 'recvonly' })
        mine.addTransceiver('audio', { direction: 'recvonly' })
        mine.ontrack = (e) => {
          const s = stream.current ?? (stream.current = new MediaStream())
          if (!s.getTracks().includes(e.track)) s.addTrack(e.track)
          if (e.track.kind === 'video') {
            const v = video.current
            if (v && 'requestVideoFrameCallback' in v) v.requestVideoFrameCallback(() => setHasFrame(true))
            else e.track.addEventListener('unmute', () => setHasFrame(true))
          }
          play()
        }
        const connected = new Promise<void>((res, rej) => {
          mine.onconnectionstatechange = () => {
            if (mine.connectionState === 'connected') res()
            else if (mine.connectionState === 'failed') rej(new Error('ICE failed'))
          }
          ctl.signal.addEventListener('abort', () => rej(new Error('timeout')))
        })
        connected.catch(() => {}) // awaited below
        await mine.setLocalDescription(await mine.createOffer())
        await new Promise<void>((res) => { // gather host candidates first (upstream has no trickle ICE)
          if (mine.iceGatheringState === 'complete') return res()
          mine.onicegatheringstatechange = () => { if (mine.iceGatheringState === 'complete') res() }
          window.setTimeout(res, 1500)
        })
        timeout = window.setTimeout(() => ctl.abort(), OFFER_TIMEOUT_MS)
        const r = await post('/offer', { sdp: mine.localDescription!.sdp, type: mine.localDescription!.type }, ctl.signal)
        const answer = parseOffer(r.status, await r.json().catch(() => null))
        if (stale()) return
        if (!answer.ok) throw new Error(answer.kind === 'busy' ? 'busy' : answer.reason)
        sid.current = answer.sessionid
        await mine.setRemoteDescription({ type: answer.type, sdp: answer.sdp })
        await connected
        window.clearTimeout(timeout)
        if (stale()) return
        attempt = 0
        setStatus('ready'); setReason(null)
        mine.onconnectionstatechange = () => { if (['failed', 'disconnected', 'closed'].includes(mine.connectionState)) fail(NOT_RUNNING) }
        // speaking state: SSE for immediacy, /is_speaking poll while SSE is down or the avatar talks (catches a missed 'end')
        es = new EventSource(`${BASE}/sse?sessionid=${encodeURIComponent(answer.sessionid)}`)
        es.onopen = () => { sseOpen = true }
        es.onerror = () => { sseOpen = false }
        es.onmessage = (m) => { const s = speakingFromEvent(m.data); if (s !== null) setTalking(s) }
        poll = window.setInterval(async () => {
          if (sseOpen && !talking) return
          try {
            const s = speakingFromPoll(await (await post('/is_speaking', { sessionid: answer.sessionid })).json())
            if (s !== null) setTalking(s)
          } catch { /* service blip: the connection handler deals with it */ }
        }, 1500)
      } catch (e) {
        window.clearTimeout(timeout)
        if (stale()) return
        const why = e instanceof Error ? e.message : ''
        fail(why === 'busy' ? NOT_RUNNING + ' (it is busy with another session)' : NOT_RUNNING)
      }
    }
    timer = window.setTimeout(() => void connect(), 0) // deferred so React's dev double-mount (or a quick mode switch) never opens a session it closes at once: the server only frees a session after its connection was up
    const onLeave = () => { try { pc?.close() } catch { /* leaving */ } }
    window.addEventListener('pagehide', onLeave)
    return () => { dead = true; window.clearTimeout(timer); window.removeEventListener('pagehide', onLeave); teardown() }
  }, [enabled, play])

  const speak = useCallback((text: string) => {
    if (sid.current && text) void post('/human', { sessionid: sid.current, text, type: 'echo', interrupt: true }).catch(() => {})
  }, [])
  const interrupt = useCallback(() => {
    if (sid.current) void post('/interrupt_talk', { sessionid: sid.current }).catch(() => {})
    setSpeaking(false)
  }, [])

  return { status, reason, speaking, hasFrame, soundBlocked, enableSound, speak, interrupt, attachVideo }
}
