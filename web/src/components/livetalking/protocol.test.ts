import assert from 'node:assert/strict'
import { test } from 'node:test'
import { backoffMs, parseOffer, speakingFromEvent, speakingFromPoll } from './protocol.ts'

test('offer answer is accepted, errors carry a reason', () => {
  const ok = parseOffer(200, { sdp: 'v=0', type: 'answer', sessionid: 42 })
  assert.deepEqual(ok, { ok: true, sdp: 'v=0', type: 'answer', sessionid: '42' })
  const busy = parseOffer(200, { code: -1, msg: 'max session reached' })
  assert.equal(busy.ok, false); assert.equal(!busy.ok && busy.kind, 'busy')
  const err = parseOffer(500, { code: -1, msg: 'boom' })
  assert.equal(!err.ok && err.kind, 'error')
  assert.equal(parseOffer(502, null).ok, false)
  assert.equal(parseOffer(200, { sdp: 'x' }).ok, false) // no sessionid
})

test('backoff doubles and caps', () => {
  assert.deepEqual([0, 1, 2, 3, 10].map(backoffMs), [2000, 4000, 8000, 16000, 30000])
})

test('speaking events and polls', () => {
  assert.equal(speakingFromEvent('{"status":"start","text":"hi"}'), true)
  assert.equal(speakingFromEvent('{"status":"end"}'), false)
  assert.equal(speakingFromEvent('{"status":"other"}'), null)
  assert.equal(speakingFromEvent('not json'), null)
  assert.equal(speakingFromPoll({ code: 0, data: true }), true)
  assert.equal(speakingFromPoll({ code: -1, msg: 'session not found' }), null)
})
