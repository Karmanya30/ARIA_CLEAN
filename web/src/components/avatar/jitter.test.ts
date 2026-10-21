import assert from 'node:assert/strict'
import { test } from 'node:test'
import { FrameQueue, MediaClock } from './jitter.ts'
import { HEADER_BYTES, MediaParser, pcm16ToFloat } from './protocol.ts'
import { conciseSpoken, emotionFor, sanitizeForSpeech } from './spoken.ts'

test('audio chunks are scheduled back to back on the clock', () => {
  const c = new MediaClock(100)
  const a = c.scheduleAudio(1000, 40, 5)
  const b = c.scheduleAudio(1040, 40, 5.01)
  assert.equal(a.rebased, false)
  assert.ok(Math.abs(a.startS - 5.1) < 1e-9)
  assert.ok(Math.abs(b.startS - a.startS - 0.04) < 1e-9)
})

test('an underrun re-anchors the clock instead of scheduling in the past', () => {
  const c = new MediaClock(100)
  c.scheduleAudio(0, 40, 1)
  const late = c.scheduleAudio(40, 40, 3) // chunk arrives 2 s late
  assert.equal(late.rebased, true)
  assert.ok(late.startS >= 3)
  const next = c.scheduleAudio(80, 40, 3.01)
  assert.ok(Math.abs(next.startS - late.startS - 0.04) < 1e-9)
})

test('a timestamp that jumps back re-anchors', () => {
  const c = new MediaClock()
  c.scheduleAudio(10000, 40, 1)
  assert.equal(c.scheduleAudio(0, 40, 1.01).rebased, true)
})

test('media time follows the clock; reset clears it', () => {
  const c = new MediaClock(100)
  assert.equal(c.mediaTimeAt(1), null)
  c.scheduleAudio(500, 40, 2) // plays at 2.1 s
  assert.ok(Math.abs(c.mediaTimeAt(2.1)! - 500) < 1e-6)
  assert.ok(Math.abs(c.mediaTimeAt(2.2)! - 600) < 1e-6)
  c.reset()
  assert.equal(c.mediaTimeAt(2.2), null)
})

test('video starts the clock when no audio plays', () => {
  const c = new MediaClock(100)
  c.startFromVideo(0, 10)
  assert.ok(Math.abs(c.mediaTimeAt(10.1)! - 0) < 1e-6)
})

test('frame queue releases the newest due frame, drops older, keeps future', () => {
  const dropped: string[] = []
  const q = new FrameQueue<string>(10, (x) => dropped.push(x))
  q.push(80, 'c'); q.push(0, 'a'); q.push(40, 'b'); q.push(200, 'future')
  assert.equal(q.takeDue(-1), undefined)
  assert.equal(q.takeDue(85), 'c')
  assert.deepEqual(dropped, ['a', 'b'])
  assert.equal(q.size, 1)
  assert.equal(q.takeDue(85), undefined)
  q.clear()
  assert.deepEqual(dropped, ['a', 'b', 'future'])
})

test('frame queue caps its size by dropping the oldest', () => {
  const dropped: number[] = []
  const q = new FrameQueue<number>(3, (x) => dropped.push(x))
  for (let i = 0; i < 5; i++) q.push(i, i)
  assert.deepEqual(dropped, [0, 1])
})

function packet(type: number, seq: number, ts: number, payload: number[], little: boolean) {
  const buf = new ArrayBuffer(HEADER_BYTES + payload.length)
  const v = new DataView(buf)
  v.setUint8(0, type); v.setUint32(1, seq, little); v.setUint32(5, ts, little)
  new Uint8Array(buf, HEADER_BYTES).set(payload)
  return buf
}

test('media header parses in either byte order', () => {
  for (const little of [false, true]) {
    const p = new MediaParser()
    const m = p.parse(packet(0x01, 7, 280, [1, 2, 3], little))!
    assert.deepEqual([m.kind, m.seq, m.ts, [...m.payload]], ['video', 7, 280, [1, 2, 3]])
    const a = p.parse(packet(0x02, 8, 320, [0, 0], little))!
    assert.deepEqual([a.kind, a.seq, a.ts], ['audio', 8, 320])
  }
  assert.equal(new MediaParser().parse(packet(0x09, 1, 1, [1], false)), null)
  assert.equal(new MediaParser().parse(new ArrayBuffer(4)), null)
})

test('pcm16 converts to floats', () => {
  const f = pcm16ToFloat(new Uint8Array([0x00, 0x40, 0x00, 0x80])) // 16384, -32768
  assert.deepEqual([...f], [0.5, -1])
})

test('speech text drops markdown, tables and symbols', () => {
  const md = '## Your plan\n\n**Insight:** You can save ₹1,50,000 a year at 12.5% & more.\n\n| Fund | Return |\n|---|---|\n| A | 10% |\n\n- Keep an *emergency* fund\n- See [the guide](http://x.y/z) 😀'
  const { text, droppedTable } = sanitizeForSpeech(md)
  assert.equal(droppedTable, true)
  assert.ok(!/[|#*[\]]/.test(text), text)
  assert.ok(text.includes('1,50,000 rupees'), text)
  assert.ok(text.includes('12.5 percent and more'), text)
  assert.ok(!text.includes('Fund'), text)
  assert.ok(text.includes('See the guide'), text)
})

test('long replies become a short spoken version pointing at the screen', () => {
  const long = Array.from({ length: 30 }, (_, i) => `Sentence number ${i} has a handful of words in it.`).join(' ')
  const out = conciseSpoken(long, 40)
  assert.ok(out.split(' ').length < 60)
  assert.ok(out.endsWith('The full details are on screen.'))
  assert.equal(conciseSpoken('Hello there.'), 'Hello there.')
})

test('emotion comes from tone, then wording', () => {
  assert.equal(emotionFor({ tone: { strategy: 'reassure' } }).emotion, 'concerned')
  assert.equal(emotionFor({ domain: 'care' }).emotion, 'concerned')
  assert.equal(emotionFor({ response: 'Congrats, you are on track!' }).emotion, 'upbeat')
  assert.equal(emotionFor({ response: 'This is a high risk product.' }).emotion, 'serious')
  assert.equal(emotionFor({ response: 'An SIP is a monthly investment.' }).emotion, 'warm')
})
