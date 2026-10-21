import { engineApi } from './engineApi'
import { FrameQueue, MediaClock } from './jitter'
import { MediaParser, pcm16ToFloat, type EngineMetrics, type EngineState, type ServerEvent, type SpeakOptions } from './protocol'

export type Connection = 'connecting' | 'open' | 'closed'

export interface ClientSnapshot {
  connection: Connection
  serverState: EngineState
  reason?: string
  playing: boolean // audio is still being played from the buffer
  hasFrame: boolean
  caption: string
  metrics: EngineMetrics
}

const PING_MS = 15_000
const SILENT_MS = 60_000
const OPEN_TIMEOUT_MS = 6_000
const MUTE_AFTER_INTERRUPT_MS = 300
const MAX_TEXT = 2000

/** WebSocket client for /stream: jitter-buffered audio (WebAudio) and canvas video in sync, interrupt, reconnect with backoff.
 * The playback clock is performance.now (video keeps running if the AudioContext is still suspended); audio is
 * scheduled on the AudioContext relative to it and video is delayed by the output latency so lips match the sound. */
export class AvatarClient {
  private ws: WebSocket | null = null
  private running = false
  private attempt = 0
  private timers: { reconnect?: number; ping?: number; open?: number; raf?: number } = {}
  private lastMessageAt = 0
  private audio: AudioContext | null = null
  private gain: GainNode | null = null
  private sources = new Set<AudioBufferSourceNode>()
  private sampleRate = 16000
  private rateAnnounced = false // an audio_format event was seen on this connection
  private rateInline = false // otherwise each audio payload starts with its u32 sample rate (avatar_engine/protocol.py)
  private clock = new MediaClock()
  private frames = new FrameQueue<ImageBitmap>(90, (b) => b.close())
  private parser = new MediaParser()
  private shown: ImageBitmap | null = null
  private canvas: HTMLCanvasElement | null = null
  private captions: { text: string; t0: number; t1: number }[] = []
  private muteUntil = 0
  private superseded = false // another tab took the session over: do not fight it by reconnecting
  private tsOf = new WeakMap<ImageBitmap, number>()
  private snap: ClientSnapshot = { connection: 'closed', serverState: 'idle', playing: false, hasFrame: false, caption: '', metrics: {} }

  private readonly replicaId: () => string | null | undefined
  private readonly look: () => { framing?: string; bg?: string }
  private readonly onChange: (s: ClientSnapshot) => void
  constructor(replicaId: () => string | null | undefined, look: () => { framing?: string; bg?: string }, onChange: (s: ClientSnapshot) => void) { this.replicaId = replicaId; this.look = look; this.onChange = onChange }

  private set(p: Partial<ClientSnapshot>) {
    const next = { ...this.snap, ...p }
    if ((Object.keys(p) as (keyof ClientSnapshot)[]).every((k) => Object.is(next[k], this.snap[k]))) return
    this.snap = next
    this.onChange(next)
  }
  private now() { return performance.now() / 1000 }

  setCanvas(el: HTMLCanvasElement | null) { this.canvas = el }

  start() {
    if (this.running) return
    this.running = true
    this.superseded = false
    this.attempt = 0
    this.connect()
    this.timers.raf = requestAnimationFrame(this.paint)
  }

  stop() {
    this.running = false
    clearTimeout(this.timers.reconnect); clearInterval(this.timers.ping); clearTimeout(this.timers.open)
    if (this.timers.raf) cancelAnimationFrame(this.timers.raf)
    this.dropSocket()
    this.flush()
    this.shown?.close(); this.shown = null
    void this.audio?.close().catch(() => {}); this.audio = null; this.gain = null
    this.set({ connection: 'closed', hasFrame: false, caption: '' })
  }

  /** Call from a click/keypress: browsers keep the AudioContext suspended until then. */
  unlock() {
    const ctx = this.ensureAudio()
    if (ctx?.state === 'suspended') void ctx.resume().catch(() => {})
  }

  speak(text: string, opts: SpeakOptions = {}): boolean {
    const clean = text.trim().slice(0, MAX_TEXT)
    if (!clean || this.ws?.readyState !== WebSocket.OPEN || this.snap.serverState === 'unavailable') return false
    this.unlock()
    this.trace('speak', 0)
    this.muteUntil = 0
    this.captions = []
    this.ws.send(JSON.stringify({ type: 'speak', text: clean, ...opts }))
    this.set({ serverState: 'thinking', caption: '' })
    return true
  }

  /** Shows the attentive pose while the user talks. */
  listening(on: boolean) {
    if (this.ws?.readyState === WebSocket.OPEN && this.snap.serverState !== 'unavailable') this.ws.send(JSON.stringify({ type: 'listening', value: on }))
  }

  /** Stops audio and clears every buffer at once, then tells the engine to stop generating. */
  interrupt() {
    this.flush()
    this.muteUntil = performance.now() + MUTE_AFTER_INTERRUPT_MS
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: 'interrupt' }))
      if (this.snap.serverState !== 'unavailable') this.set({ serverState: 'idle' })
    }
  }

  private flush() {
    for (const s of this.sources) { s.onended = null; try { s.stop() } catch { /* already stopped */ } s.disconnect() }
    this.sources.clear()
    this.frames.clear()
    this.clock.reset()
    this.captions = []
    this.set({ playing: false, caption: '' })
  }

  private ensureAudio(): AudioContext | null {
    if (this.audio) return this.audio
    try {
      this.audio = new AudioContext({ latencyHint: 'interactive' })
      this.gain = this.audio.createGain()
      this.gain.connect(this.audio.destination)
    } catch { this.audio = null }
    return this.audio
  }

  private dropSocket() {
    const ws = this.ws
    this.ws = null
    clearInterval(this.timers.ping); clearTimeout(this.timers.open)
    if (ws) { ws.onopen = ws.onmessage = ws.onclose = ws.onerror = null; try { ws.close() } catch { /* closing anyway */ } }
  }

  private connect() {
    if (!this.running) return
    this.dropSocket()
    this.set({ connection: 'connecting' })
    let ws: WebSocket
    try { ws = new WebSocket(engineApi.streamUrl(this.replicaId(), this.look())) } catch { this.scheduleReconnect(); return }
    ws.binaryType = 'arraybuffer'
    this.ws = ws
    this.timers.open = window.setTimeout(() => { if (ws.readyState !== WebSocket.OPEN) this.lost(ws) }, OPEN_TIMEOUT_MS)
    ws.onopen = () => {
      clearTimeout(this.timers.open)
      this.attempt = 0
      this.lastMessageAt = performance.now()
      this.parser = new MediaParser()
      this.rateAnnounced = this.rateInline = false
      this.set({ connection: 'open', serverState: 'idle', reason: undefined })
      this.timers.ping = window.setInterval(() => {
        if (performance.now() - this.lastMessageAt > SILENT_MS) { this.lost(ws); return }
        if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: 'ping' }))
      }, PING_MS)
    }
    ws.onmessage = (e) => {
      this.lastMessageAt = performance.now()
      if (typeof e.data === 'string') this.onEvent(e.data)
      else if (e.data instanceof ArrayBuffer) this.onMedia(e.data)
    }
    ws.onclose = () => this.lost(ws)
    ws.onerror = () => {} // onclose follows
  }

  private lost(ws: WebSocket) {
    if (this.ws !== ws) return
    this.dropSocket()
    this.flush()
    this.set({ connection: 'closed' })
    this.scheduleReconnect()
  }

  /** Take the session back after another tab replaced it. */
  reconnect() {
    if (!this.running) return
    this.superseded = false
    this.attempt = 0
    clearTimeout(this.timers.reconnect)
    this.connect()
  }

  private scheduleReconnect() {
    if (!this.running || this.superseded) return
    const wait = Math.min(10_000, 500 * 2 ** this.attempt++) * (0.8 + Math.random() * 0.4)
    this.timers.reconnect = window.setTimeout(() => this.connect(), wait)
  }

  private onEvent(raw: string) {
    let ev: ServerEvent
    try { ev = JSON.parse(raw) } catch { return }
    switch (ev.type) {
      case 'audio_format':
        if (ev.sample_rate >= 8000 && ev.sample_rate <= 96000) this.sampleRate = ev.sample_rate
        this.rateAnnounced = true
        break
      case 'state':
        if (ev.value === 'idle') this.muteUntil = 0
        if (ev.value === 'unavailable' && /replaced/i.test(ev.reason ?? '')) this.superseded = true
        this.set({ serverState: ev.value, reason: ev.reason })
        break
      case 'caption':
        this.captions.push({ text: ev.text, t0: ev.t_start, t1: ev.t_end })
        break
      case 'metrics':
        this.set({ metrics: { ttfb_ms: ev.ttfb_ms, fps: ev.fps, gen_ms: ev.gen_ms } })
        break
    }
  }

  private onMedia(buf: ArrayBuffer) {
    const m = this.parser.parse(buf)
    if (!m || performance.now() < this.muteUntil) return
    if (m.kind === 'audio') {
      let pcm = m.payload
      if (!this.rateAnnounced && pcm.byteLength > 4) this.rateInline = true
      if (this.rateInline && pcm.byteLength > 4) {
        const rate = new DataView(pcm.buffer, pcm.byteOffset, 4).getUint32(0, true)
        if (rate >= 8000 && rate <= 96000) this.sampleRate = rate
        pcm = pcm.subarray(4)
      }
      this.playAudio(m.ts, pcm16ToFloat(pcm))
    }
    else {
      if (!this.clock.started) this.clock.startFromVideo(m.ts, this.now())
      createImageBitmap(new Blob([m.payload as BlobPart], { type: m.payload[0] === 0x52 ? 'image/webp' : 'image/jpeg' })).then(
        (bm) => { if (this.running && performance.now() >= this.muteUntil) { this.tsOf.set(bm, m.ts); this.frames.push(m.ts, bm) } else bm.close() },
        () => {}, // a corrupt frame is skipped
      )
    }
  }

  private playAudio(ts: number, pcm: Float32Array) {
    const ctx = this.ensureAudio()
    if (!ctx || !this.gain || !pcm.length) return
    const buf = ctx.createBuffer(1, pcm.length, this.sampleRate)
    buf.copyToChannel(pcm as Float32Array<ArrayBuffer>, 0)
    const { startS } = this.clock.scheduleAudio(ts, (pcm.length / this.sampleRate) * 1000, this.now())
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(this.gain)
    src.onended = () => { this.sources.delete(src); src.disconnect(); if (!this.sources.size) this.set({ playing: false }) }
    const when = Math.max(ctx.currentTime, ctx.currentTime + (startS - this.now()))
    src.start(when)
    this.trace('audio', ts, when, ctx)
    this.sources.add(src)
    this.set({ playing: true })
  }

  /** Test hook: when window.__avTrace is an array, playback events are appended (used to measure latency and a/v drift). */
  private trace(kind: string, ts: number, when?: number, ctx?: AudioContext) {
    const t = (window as unknown as { __avTrace?: unknown[] }).__avTrace
    if (!Array.isArray(t)) return
    let at = performance.now()
    if (ctx && when !== undefined) { const o = ctx.getOutputTimestamp(); at = (o.performanceTime ?? at) + (when - (o.contextTime ?? 0)) * 1000 }
    t.push({ kind, ts, at })
  }

  private paint = () => {
    this.timers.raf = requestAnimationFrame(this.paint)
    if (document.hidden) return
    const latency = this.audio ? (this.audio.outputLatency || this.audio.baseLatency || 0) : 0
    const mediaMs = this.clock.mediaTimeAt(this.now() - latency)
    if (mediaMs === null) return
    const frame = this.frames.takeDue(mediaMs)
    const canvas = this.canvas
    if (frame && canvas) {
      if (canvas.width !== frame.width || canvas.height !== frame.height) { canvas.width = frame.width; canvas.height = frame.height }
      const g = canvas.getContext('2d')
      g?.clearRect(0, 0, canvas.width, canvas.height) // transparent (WebP) frames would pile up
      g?.drawImage(frame, 0, 0)
      this.shown?.close()
      this.shown = frame
      this.trace('video', this.tsOf.get(frame) ?? 0)
      this.set({ hasFrame: true })
    } else if (frame) frame.close()
    // ponytail: captions are matched by stream time; if the engine's t_start/t_end use another base they show late or never.
    const cap = this.captions.find((c) => mediaMs >= c.t0 && mediaMs < Math.max(c.t1, c.t0 + 400))
    this.set({ caption: cap ? cap.text : this.snap.playing ? this.snap.caption : '' })
  }
}
