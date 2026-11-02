import { test, expect, type Page, type WebSocketRoute } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

// Exercise the real meeting + iframe controller and real Web Audio decoding, with
// deterministic provider boundaries. No microphone, LLM or GPU service is used.
const pageHtml = readFileSync(path.resolve('../interface/avatar/live.html'), 'utf8')
const talkingHead = `export class TalkingHead {
  constructor(el) { this.audioCtx = new AudioContext(); this.sources = []; this.mtAvatar = {}; this.opt = {}; this.endAt = 0; el.innerHTML = '<div style="height:100%;display:grid;place-items:center;color:#a2dfc6">Avatar renderer test fixture</div>'; }
  async showAvatar() {} lookAtCamera() {} start() {} stop() {}
  speakAudio(clip) {
    const at = Math.max(this.audioCtx.currentTime + .02, this.endAt);
    const src = this.audioCtx.createBufferSource(); src.buffer = clip.audio; src.connect(this.audioCtx.destination);
    src.start(at); this.endAt = at + clip.audio.duration; this.sources.push(src); this.isSpeaking = true;
    const timer = setTimeout(() => clip.markers?.[0](), (at - this.audioCtx.currentTime) * 1000);
    src.onended = () => { clearTimeout(timer); this.sources = this.sources.filter(s => s !== src); this.isSpeaking = this.sources.length > 0; };
  }
  stopSpeaking() { this.sources.forEach(s => s.stop()); this.sources = []; this.isSpeaking = false; this.endAt = 0; }
}`
function audio(seconds = 2) {
  const rate = 16000, samples = rate * seconds, wav = Buffer.alloc(44 + samples * 2)
  wav.write('RIFF'); wav.writeUInt32LE(wav.length - 8, 4); wav.write('WAVEfmt ', 8)
  wav.writeUInt32LE(16, 16); wav.writeUInt16LE(1, 20); wav.writeUInt16LE(1, 22)
  wav.writeUInt32LE(rate, 24); wav.writeUInt32LE(rate * 2, 28); wav.writeUInt16LE(2, 32); wav.writeUInt16LE(16, 34)
  wav.write('data', 36); wav.writeUInt32LE(samples * 2, 40)
  for (let i = 0; i < samples; i++) wav.writeInt16LE(Math.round(Math.sin(i * 440 * Math.PI * 2 / rate) * 2000), 44 + i * 2)
  return wav.toString('base64')
}

async function setup(page: Page, version = 'v2', supported = true) {
  const errors: string[] = [], requests: any[] = [], history: any[] = [], sockets: WebSocketRoute[] = []
  let frameLoads = 0
  page.on('pageerror', e => errors.push(e.message))
  await page.addInitScript(({ version, supported }) => {
    localStorage.setItem('aria_version', version)
    localStorage.setItem('aria_adapt_tone', 'off')
    class Recognition {
      onstart?: () => void; onend?: () => void; onerror?: (e: any) => void; onresult?: (e: any) => void
      start() { (window as any).recognizer = this; setTimeout(() => this.onstart?.(), 0) }
      abort() { (window as any).aborts = ((window as any).aborts || 0) + 1; this.onend?.() }
    }
    Object.defineProperty(window, 'SpeechRecognition', { value: supported ? Recognition : undefined })
    Object.defineProperty(window, 'webkitSpeechRecognition', { value: undefined })
    // These tests exercise the Web Speech fallback independently of recording.
    Object.defineProperty(window, 'MediaRecorder', { value: undefined })
  }, { version, supported })
  await page.route('**/avatar/live?*', route => {
    frameLoads++
    return route.fulfill({ contentType: 'text/html', body: pageHtml.replace('const SESSION =', 'params.set("avatar", "3d");\nconst SESSION =') })
  })
  await page.route('**/TalkingHead@*/modules/talkinghead.mjs', route => route.fulfill({ contentType: 'text/javascript', body: talkingHead }))
  await page.route('**/HeadAudio@*/**', route => route.abort())
  await page.route('**/api/chat/history?*', route => route.fulfill({ json: { history } }))
  await page.routeWebSocket('**/api/live/ws', socket => {
    sockets.push(socket)
    socket.onMessage(data => { requests.push(JSON.parse(String(data))) })
  })
  await page.goto('/#/chat')
  const frame = page.frameLocator('iframe[title="ARIA live avatar"]')
  await frame.getByRole('button', { name: 'Start conversation' }).click()
  await expect(page.locator('.meeting-status')).toContainText(supported ? 'Microphone muted' : 'Voice input needs')
  const emit = (m: any) => sockets.at(-1)!.send(JSON.stringify(m))
  return { errors, requests, history, sockets, frame, emit, loads: () => frameLoads }
}

for (const version of ['v2']) {
  test(`${version}: shared chat, playback captions, mute, interrupt and end`, async ({ page }) => {
    const app = await setup(page, version)
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await expect(page.locator('.meeting-status')).toHaveText('Listening to you…')
    await app.frame.locator('body').evaluate(() => {
      const r = (window as any).recognizer
      r.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: 'Explain a SIP' }], { isFinal: true })] })
    })
    await expect.poll(() => app.requests.filter(m => m.type === 'user').length).toBe(1)
    const first = app.requests.find(m => m.type === 'user')
    expect(first.owner_id).toBeTruthy()
    app.emit({ type: 'text', turn: first.turn, delta: 'First sentence. Second sentence.' })
    await expect(app.frame.locator('#caption')).not.toContainText('Second sentence.')
    app.emit({ type: 'audio', turn: first.turn, text: 'First sentence.', audio: audio(8), mime: 'audio/wav' })
    app.emit({ type: 'audio', turn: first.turn, text: 'Second sentence.', audio: audio(3), mime: 'audio/wav' })
    await expect(app.frame.locator('#caption')).toHaveText('First sentence.')
    await page.getByRole('button', { name: 'Toggle chat' }).click()
    await expect(page.getByRole('textbox', { name: 'Message ARIA' })).toBeFocused()
    expect(app.loads()).toBe(1)
    await expect(page.locator('.meeting-messages')).toContainText('Explain a SIP')
    await page.getByRole('button', { name: 'Mute microphone', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Unmute microphone' })).toBeVisible()
    await expect(app.frame.locator('#caption')).toHaveText('First sentence.')
    await page.getByRole('button', { name: 'Toggle captions' }).click()
    await expect(app.frame.locator('#caption')).toBeHidden()
    await expect(page.getByRole('button', { name: 'Interrupt ARIA' })).toBeEnabled()
    await page.getByRole('button', { name: 'Toggle captions' }).click()
    await expect(app.frame.locator('#caption')).toBeVisible()
    await page.getByRole('textbox', { name: 'Message ARIA' }).fill('What about risk?')
    await page.getByRole('button', { name: 'Send message', exact: true }).click()
    await expect.poll(() => app.requests.filter(m => m.type === 'user').length).toBe(2)
    const second = app.requests.filter(m => m.type === 'user')[1]
    expect(second.session_id).toBe(first.session_id)
    expect(second.turn).toBeGreaterThan(first.turn)
    app.emit({ type: 'audio', turn: first.turn, text: 'Stale audio', audio: audio(), mime: 'audio/wav' })
    app.history.push({ query: 'What about risk?', response: { domain: 'general', response: '**Diversify.**\n\n| Asset | Risk |\n| --- | --- |\n| Equity | High |' } })
    app.emit({ type: 'done', turn: second.turn, text: 'Diversify.' })
    await expect(page.locator('.meeting-chat table')).toBeVisible()
    await expect(app.frame.locator('#caption')).not.toContainText('Stale audio')
    await page.getByRole('textbox', { name: 'Message ARIA' }).press('Escape')
    await expect(page.getByRole('button', { name: 'Toggle chat' })).toBeFocused()
    await expect(page.locator('.meeting-chat')).toBeHidden()
    expect(app.loads()).toBe(1)
    await page.getByRole('button', { name: 'End session', exact: true }).click()
    await expect(page.getByRole('combobox', { name: 'Mode', exact: true })).toHaveValue('Normal Mode')
    await expect(page.locator('iframe[title="ARIA live avatar"]')).toHaveCount(0)
    await expect(page.getByText('Diversify.', { exact: false }).first()).toBeVisible()
    expect(app.errors).toEqual([])
  })
}

test('permission denial, late recognition, reconnect and unsent message confirmation', async ({ page }) => {
  const app = await setup(page)
  await page.getByRole('button', { name: 'Start listening', exact: true }).click()
  await expect(page.locator('.meeting-status')).toHaveText('Listening to you…')
  await app.frame.locator('body').evaluate(() => (window as any).recognizer.onerror({ error: 'not-allowed' }))
  await expect(page.getByRole('alert')).toContainText('Microphone access was denied')
  await app.frame.locator('body').evaluate(() => (window as any).recognizer.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: 'Late question' }], { isFinal: true })] }))
  expect(app.requests.filter(m => m.type === 'user')).toHaveLength(0)
  app.sockets[0].close({ code: 1011, reason: 'Test disconnect' })
  await expect.poll(() => app.sockets.length).toBe(2)
  await expect(page.locator('.meeting-connection')).toContainText('Connected')
  await page.getByRole('button', { name: 'Toggle chat' }).click()
  await page.getByRole('textbox', { name: 'Message ARIA' }).fill('Unsent draft')
  await page.getByRole('button', { name: 'End session', exact: true }).click()
  await expect(page.getByRole('alertdialog')).toContainText('unsent message')
  await page.getByRole('button', { name: 'Stay in meeting' }).click()
  await expect(page.getByRole('textbox', { name: 'Message ARIA' })).toHaveValue('Unsent draft')
  await page.getByRole('button', { name: 'End session', exact: true }).click()
  await page.getByRole('alertdialog').getByRole('button', { name: 'Leave meeting' }).click()
  await expect(page.getByRole('dialog', { name: 'ARIA Live meeting' })).toHaveCount(0)
  expect(app.errors).toEqual([])
})

test('unsupported speech remains usable through chat at every requested viewport', async ({ page }) => {
  const app = await setup(page, 'v2', false)
  await expect(page.getByRole('button', { name: 'Unmute microphone' })).toBeDisabled()
  for (const [width, height] of [[1920,1080],[1536,864],[1366,768],[1024,768],[768,1024],[390,844]]) {
    await page.setViewportSize({ width, height })
    for (const open of [true, false]) {
      await page.getByRole('button', { name: 'Toggle chat' }).click()
      await expect(page.getByRole('button', { name: 'Toggle chat' })).toHaveAttribute('aria-expanded', String(open))
      await expect(page.getByRole('button', { name: 'End session', exact: true })).toBeInViewport()
      await expect(page.locator('.meeting-stage')).toBeInViewport()
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    }
  }
  expect(app.loads()).toBe(1)
  expect(app.errors).toEqual([])
})

test('captions advance only when queued audio starts and interruption clears future captions', async ({ page }) => {
  const app = await setup(page)
  await page.getByRole('button', { name: 'Toggle chat' }).click()
  await page.getByRole('textbox', { name: 'Message ARIA' }).fill('Explain diversification')
  await page.getByRole('button', { name: 'Send message', exact: true }).click()
  await expect.poll(() => app.requests.length).toBe(1)
  const turn = app.requests[0].turn
  app.emit({ type: 'text', turn, delta: 'First sentence. Second sentence. Third sentence.' })
  for (const text of ['First sentence.', 'Second sentence.', 'Third sentence.']) app.emit({ type: 'audio', turn, text, audio: audio(2), mime: 'audio/wav' })
  app.emit({ type: 'done', turn, text: 'First sentence. Second sentence. Third sentence.' })
  await expect(app.frame.locator('#caption')).toHaveText('First sentence.')
  await expect(app.frame.locator('#caption')).toHaveText('Second sentence.')
  await expect(page.getByRole('button', { name: 'Interrupt ARIA' })).toBeEnabled()
  await page.getByRole('button', { name: 'Interrupt ARIA' }).click()
  await expect(app.frame.locator('#caption')).toBeEmpty()
  await page.waitForTimeout(2300)
  await expect(app.frame.locator('#caption')).toBeEmpty()
  expect(app.requests.filter(m => m.type === 'interrupt')).toHaveLength(1)
  expect(app.errors).toEqual([])
})

for (const action of ['finish', 'silence', 'mute']) {
  test(`interim speech: ${action} commits once or discards on explicit mute`, async ({ page }) => {
    const app = await setup(page)
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await expect(page.locator('.meeting-status')).toHaveText('Listening to you…')
    await app.frame.locator('body').evaluate(() => {
      const r = (window as any).recognizer
      r.onresult({ resultIndex: 0, results: [Object.assign([{ transcript: 'Hello ARIA' }], { isFinal: false })] })
    })
    if (action === 'finish') await page.getByRole('button', { name: 'Finish speaking', exact: true }).click()
    if (action === 'mute') await page.getByRole('button', { name: 'Mute microphone', exact: true }).click()
    await page.waitForTimeout(2200)
    expect(app.requests.filter(m => m.type === 'user')).toHaveLength(action === 'mute' ? 0 : 1)
    expect(app.errors).toEqual([])
  })
}

test('configured avatar renders in the meeting with real assets', async ({ page }, info) => {
  test.skip(!process.env.ARIA_REAL_AVATAR_SMOKE, 'Opt-in smoke test downloads the existing avatar model dependencies.')
  await page.addInitScript(() => {
    localStorage.setItem('aria_version', 'v2')
    Object.defineProperty(window, 'SpeechRecognition', { value: undefined })
    Object.defineProperty(window, 'webkitSpeechRecognition', { value: undefined })
  })
  let socket: WebSocketRoute
  const history: any[] = []
  await page.route('**/api/chat/history?*', route => route.fulfill({ json: { history } }))
  await page.routeWebSocket('**/api/live/ws', ws => { socket = ws; ws.onMessage(data => {
    const m = JSON.parse(String(data))
    if (m.type === 'user') {
      history.push({ query: m.text, response: { domain: 'general', response: 'A clearer view of your finances.' } })
      socket.send(JSON.stringify({ type: 'audio', turn: m.turn, text: 'A clearer view of your finances.', audio: audio(6), mime: 'audio/wav' }))
      socket.send(JSON.stringify({ type: 'done', turn: m.turn, text: 'A clearer view of your finances.' }))
    }
  }) })
  await page.goto('/#/chat')
  const frame = page.frameLocator('iframe[title="ARIA live avatar"]')
  await frame.getByRole('button', { name: 'Start conversation' }).click({ timeout: 65000 })
  await expect(frame.locator('#avatar canvas')).toBeVisible()
  await page.screenshot({ path: info.outputPath('meeting-desktop.png') })
  await page.getByRole('button', { name: 'Toggle chat' }).click()
  await page.getByRole('textbox', { name: 'Message ARIA' }).fill('Hello ARIA')
  await page.getByRole('button', { name: 'Send message', exact: true }).click()
  await expect(frame.locator('#caption')).toHaveText('A clearer view of your finances.')
  await page.screenshot({ path: info.outputPath('meeting-chat.png') })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Close chat' }).click()
  await expect(page.locator('.meeting-chat')).toBeHidden()
  await page.screenshot({ path: info.outputPath('meeting-mobile.png') })
})
