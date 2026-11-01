/** Real live voice test with a synthetic microphone recording; no provider mocks. */
import { createRequire } from 'node:module'
import { randomUUID, randomBytes } from 'node:crypto'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const { chromium, expect } = createRequire(path.join(root, 'web/package.json'))('@playwright/test')
const base = process.env.ARIA_DRY_RUN_URL || 'http://localhost:5173'
if (!['localhost', '127.0.0.1'].includes(new URL(base).hostname)) throw new Error('Local ARIA only')
const output = path.join(root, '.audit/live-microphone')
await mkdir(output, { recursive: true })
const report = { complete: false, source: 'Synthetic speech WAV played through Chromium fake microphone; actual recorder, Whisper, WebSocket, LLM and TTS', errors: [], requests: [], frames: [] }
const browser = await chromium.launch({ channel: 'chromium', headless: true, args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream', `--use-file-for-fake-audio-capture=${path.join(output, 'question.wav')}%noloop`] })
const context = await browser.newContext({ permissions: ['microphone'], viewport: { width: 1440, height: 900 } })
const page = await context.newPage()
page.on('pageerror', e => report.errors.push(e.message))
page.on('response', r => { if (r.url().includes('/api/voice/transcribe')) report.requests.push({ status: r.status(), path: '/api/voice/transcribe' }) })
page.on('websocket', ws => {
  if (!ws.url().includes('/api/live/ws')) return
  ws.on('framesent', ({ payload }) => { try { const m = JSON.parse(String(payload)); if (m.type === 'user') report.frames.push({ type: 'user', text: m.text, turn: m.turn }) } catch {} })
  ws.on('framereceived', ({ payload }) => { try { const m = JSON.parse(String(payload)); if (['accepted', 'audio', 'done', 'error'].includes(m.type)) report.frames.push({ type: m.type, turn: m.turn, text: m.type === 'done' ? m.text : undefined }) } catch {} })
})
try {
  const registration = await context.request.post(base + '/api/auth/register', { headers: { Origin: base }, data: { email: `mic-qa-${randomUUID()}@example.test`, password: randomBytes(24).toString('base64url') } })
  if (!registration.ok()) throw new Error('QA registration failed: ' + registration.status())
  await page.addInitScript(() => localStorage.setItem('aria_version', 'v2'))
  await page.goto(base + '/#/chat')
  const frame = page.frameLocator('iframe[title="ARIA live avatar"]')
  await frame.getByRole('button', { name: 'Start conversation' }).click({ timeout: 90000 })
  await page.getByRole('button', { name: 'Start listening', exact: true }).click()
  await expect.poll(() => report.frames.some(f => f.type === 'user'), { timeout: 90000 }).toBe(true)
  await expect.poll(() => report.frames.some(f => f.type === 'done'), { timeout: 150000 }).toBe(true)
  await expect.poll(() => report.frames.some(f => f.type === 'audio'), { timeout: 30000 }).toBe(true)
  await expect(frame.locator('#caption')).not.toBeEmpty({ timeout: 30000 })
  await page.screenshot({ path: path.join(output, 'voice-reply.png') })
  report.complete = true
} catch (e) { report.failure = e.message; process.exitCode = 1; await page.screenshot({ path: path.join(output, 'failure.png') }).catch(() => {}) }
finally { await writeFile(path.join(output, 'result.json'), JSON.stringify(report, null, 2)); await browser.close(); console.log(JSON.stringify(report)) }
