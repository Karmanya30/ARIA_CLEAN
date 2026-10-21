/** Timestamp-driven playback scheduling for the avatar stream: audio is scheduled on the WebAudio clock and
 * video frames are shown when the audio clock reaches their timestamp, so lips stay in sync with the voice. */

/** Maps stream timestamps (ms) onto the audio clock (seconds). */
export class MediaClock {
  private base: { ts: number; at: number } | null = null
  private audioEndTs = 0
  /** How far ahead of "now" the first chunk is scheduled, so later chunks can arrive late without a gap. */
  readonly prebufferMs: number
  readonly lateToleranceMs: number
  constructor(prebufferMs = 120, lateToleranceMs = 30) { this.prebufferMs = prebufferMs; this.lateToleranceMs = lateToleranceMs }

  get started() { return this.base !== null }

  /** Start the clock from the first video frame when no audio is playing (idle loop). */
  startFromVideo(ts: number, nowS: number) {
    if (!this.base) this.base = { ts, at: nowS + this.prebufferMs / 1000 }
  }

  /** Returns the audio-clock time (s) at which this chunk must start. A chunk that would start in the past
   * (underrun) or whose timestamp jumped back re-anchors the clock to "now" and reports `rebased`. */
  scheduleAudio(ts: number, durationMs: number, nowS: number): { startS: number; rebased: boolean } {
    let rebased = false
    if (!this.base) this.base = { ts, at: nowS + this.prebufferMs / 1000 }
    let startS = this.base.at + (ts - this.base.ts) / 1000
    if (startS < nowS - this.lateToleranceMs / 1000 || ts < this.audioEndTs - 1000) {
      this.base = { ts, at: nowS + this.prebufferMs / 1000 / 2 }
      startS = this.base.at
      rebased = true
    }
    this.audioEndTs = ts + durationMs
    return { startS, rebased }
  }

  /** Stream time (ms) currently being heard/seen, or null before anything was scheduled. */
  mediaTimeAt(nowS: number): number | null {
    return this.base ? this.base.ts + (nowS - this.base.at) * 1000 : null
  }

  reset() { this.base = null; this.audioEndTs = 0 }
}

/** Frames ordered by timestamp. `takeDue` returns the newest frame whose time has come and drops older ones. */
export class FrameQueue<T> {
  private items: { ts: number; item: T }[] = []
  private readonly maxFrames: number
  private readonly onDrop: (item: T) => void
  constructor(maxFrames = 90, onDrop: (item: T) => void = () => {}) { this.maxFrames = maxFrames; this.onDrop = onDrop }

  get size() { return this.items.length }

  push(ts: number, item: T) {
    let i = this.items.length
    while (i > 0 && this.items[i - 1].ts > ts) i--
    this.items.splice(i, 0, { ts, item })
    while (this.items.length > this.maxFrames) this.onDrop(this.items.shift()!.item)
  }

  takeDue(mediaMs: number): T | undefined {
    let due = -1
    while (due + 1 < this.items.length && this.items[due + 1].ts <= mediaMs) due++
    if (due < 0) return undefined
    for (let i = 0; i < due; i++) this.onDrop(this.items[i].item)
    const picked = this.items[due].item
    this.items.splice(0, due + 1)
    return picked
  }

  clear() { for (const f of this.items) this.onDrop(f.item); this.items = [] }
}
