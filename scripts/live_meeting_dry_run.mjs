/** Opt-in real-provider QA against a running local ARIA. No response/voice mocks.
 * Creates a distinct QA account through normal registration; never touches existing users.
 * Run: node scripts/live_meeting_dry_run.mjs
 */
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import { randomUUID, randomBytes } from 'node:crypto'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'web/package.json'))
const { chromium, expect } = require('@playwright/test')
const base = process.env.ARIA_DRY_RUN_URL || 'http://localhost:5173'
if (!['localhost', '127.0.0.1'].includes(new URL(base).hostname)) throw new Error('This QA runner is restricted to local ARIA.')
const output = path.join(root, '.audit/live3')
await mkdir(output, { recursive: true })
const report = { at: new Date().toISOString(), base, questions: [], endpoints: [], pageErrors: [], networkFailures: [], screenshots: [], microphone: 'NOT VERIFIED: no human microphone input', complete: false }
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1536, height: 864 } })
const page = await context.newPage()
page.setDefaultTimeout(20000)
const received = [], sent = []
let sample = null, hasText = false
page.on('pageerror', e => report.pageErrors.push(e.message))
page.on('requestfailed', r => report.networkFailures.push({ url: r.url().split('?')[0], error: r.failure()?.errorText }))
page.on('websocket', ws => {
  if (!ws.url().includes('/api/live/ws')) return
  ws.on('framesent', ({ payload }) => { try { const m = JSON.parse(String(payload)); if (m.type === 'user') { sent.push(m); hasText = false } } catch {} })
  ws.on('framereceived', ({ payload }) => {
    try {
      const m = JSON.parse(String(payload))
      if (m.type === 'text') hasText = true
      if (m.type === 'audio' && hasText && !sample) sample = { bytes: Buffer.from(m.audio, 'base64'), mime: m.mime, text: m.text }
      received.push({ ...m, audio: undefined, audioBytes: m.audio ? Math.floor(m.audio.length * .75) : undefined, receivedAt: Date.now() })
    } catch {}
  })
})
async function shot(name) { await page.screenshot({ path: path.join(output, name + '.png') }); report.screenshots.push(name + '.png') }
try {
  const health = await context.request.get(base + '/api/health')
  report.endpoints.push({ path: '/api/health', status: health.status(), data: await health.json() })
  const registration = await context.request.post(base + '/api/auth/register', { headers: { Origin: base }, data: { email: `live-qa-${randomUUID()}@example.test`, password: randomBytes(24).toString('base64url') } })
  if (!registration.ok()) throw new Error('QA account registration failed: HTTP ' + registration.status())
  const owner = (await registration.json()).user.id
  report.account = owner
  await page.addInitScript(() => localStorage.setItem('aria_version', 'v2'))
  await page.goto(base + '/#/chat')
  const frame = page.frameLocator('iframe[title="ARIA live avatar"]')
  await expect(page.locator('.meeting-official-logo img')).toHaveAttribute('src', '/brand/aria-mark-128.png')
  await frame.getByRole('button', { name: 'Start conversation' }).click({ timeout: 90000 })
  report.renderer = await frame.locator('body').evaluate(() => window.__ariaLive.kind())
  await expect(frame.locator('#office')).toBeVisible()
  const office = await context.request.get(base + '/avatar/office.webp')
  report.endpoints.push({ path: '/avatar/office.webp', status: office.status(), bytes: (await office.body()).length })
  await shot('01-office-ready')
  await page.getByRole('button', { name: 'Toggle chat' }).click()
  const questions = [
    'Hello ARIA, introduce yourself and explain what you can help me with.',
    'Explain the difference between Nifty 50 and Sensex.',
    "What factors influence today's Indian stock market?",
    "Explain what a bond's duration means.",
    "Can you analyse a company's financial fundamentals?",
  ]
  for (const [index, query] of questions.entries()) {
    const start = Date.now(), before = sent.length
    await page.getByRole('textbox', { name: 'Message ARIA' }).fill(query)
    await page.getByRole('button', { name: 'Send message', exact: true }).click()
    await expect.poll(() => sent.length, { timeout: 10000 }).toBe(before + 1)
    const turn = sent.at(-1).turn
    await expect.poll(() => received.some(m => m.turn === turn && ['done', 'error'].includes(m.type)), { timeout: 150000 }).toBe(true)
    const events = received.filter(m => m.turn === turn)
    const done = events.find(m => m.type === 'done'), error = events.find(m => m.type === 'error')
    const result = { query, turn, elapsedMs: Date.now() - start, response: done?.text, error: error?.message, audioChunks: events.filter(m => m.type === 'audio').length, accepted: events.some(m => m.type === 'accepted'), timings: done?.timings }
    report.questions.push(result)
    console.log(JSON.stringify({ question: index + 1, ...result }))
    if (!done || !done.text?.trim()) throw new Error('No complete response for question ' + (index + 1))
    await expect(frame.locator('#caption')).not.toBeEmpty({ timeout: 30000 })
    if (index === 0) {
      await shot('02-speaking-captions-chat')
      await page.getByRole('button', { name: 'Toggle captions' }).click()
      await expect(frame.locator('#caption')).toBeHidden()
      await page.getByRole('button', { name: 'Toggle captions' }).click()
      await expect(frame.locator('#caption')).toBeVisible()
      await expect(page.locator('.meeting-status')).toContainText('Microphone muted', { timeout: 120000 })
      report.fullPlaybackCompleted = true
    } else if (await page.getByRole('button', { name: 'Interrupt ARIA' }).isVisible()) {
      await page.getByRole('button', { name: 'Interrupt ARIA' }).click()
    }
  }
  const session = sent[0].session_id
  report.sameSession = sent.every(m => m.session_id === session && m.owner_id === owner)
  const paths = ['/api/auth/session', `/api/chat/history?session_id=${session}&owner_id=${owner}`, `/api/profile?session_id=${owner}`, `/api/progress?session_id=${session}`, `/api/research/reports?owner_id=${owner}`, '/api/markets/overview', '/api/markets/news', '/api/instruments/search?q=Reliance']
  for (const endpoint of paths) {
    try {
      const response = await context.request.get(base + endpoint, { timeout: 45000 })
      const data = await response.json()
      report.endpoints.push({ path: endpoint.split('?')[0], status: response.status(), ...(data.history ? { historyCount: data.history.length, history: data.history } : { data }) })
    } catch (e) { report.endpoints.push({ path: endpoint.split('?')[0], error: e.message.slice(0, 200) }) }
  }
  if (sample) {
    await writeFile(path.join(output, 'real-tts-sample.' + (sample.mime === 'audio/wav' ? 'wav' : 'mp3')), sample.bytes)
    const transcription = await context.request.post(base + '/api/voice/transcribe', { headers: { Origin: base }, multipart: { file: { name: sample.mime === 'audio/wav' ? 'sample.wav' : 'sample.mp3', mimeType: sample.mime, buffer: sample.bytes } }, timeout: 120000 })
    report.transcription = { status: transcription.status(), expected: sample.text, actual: await transcription.json(), source: 'Real generated TTS audio submitted to configured Whisper; not a human microphone test' }
    console.log('TRANSCRIPTION', JSON.stringify(report.transcription))
  }
  await shot('03-transcript')
  await page.getByRole('button', { name: 'Close chat' }).click()
  await expect(page.locator('.meeting-chat')).toBeHidden()
  await page.setViewportSize({ width: 390, height: 844 })
  await shot('04-mobile-office')
  await page.getByRole('button', { name: 'Toggle chat' }).click()
  await expect(page.getByRole('textbox', { name: 'Message ARIA' })).toBeFocused()
  await shot('05-mobile-chat')
  await page.getByRole('button', { name: 'End session', exact: true }).click()
  await expect(page.getByRole('combobox', { name: 'Mode', exact: true })).toHaveValue('Normal Mode')
  report.sessionEnded = true
  report.complete = true
} catch (e) { report.failure = e.message; console.error('DRY_RUN_FAILED', e.message); await shot('failure').catch(() => {}); process.exitCode = 1 }
finally {
  await writeFile(path.join(output, 'real-dry-run.json'), JSON.stringify(report, null, 2))
  await browser.close()
  console.log('REPORT', path.join(output, 'real-dry-run.json'))
}
