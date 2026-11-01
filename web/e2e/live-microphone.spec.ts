import { test, expect, type WebSocketRoute } from '@playwright/test'
import { readFileSync } from 'node:fs'
import path from 'node:path'

// Real Chromium MediaRecorder and synthetic device; transcription and socket are
// controlled here. The separate live_microphone_dry_run uses real providers.
test.use({ channel: 'chromium', permissions: ['microphone'], launchOptions: { args: ['--use-fake-device-for-media-stream'] } })
const html = readFileSync(path.resolve('../interface/avatar/live.html'), 'utf8')
const head = `export class TalkingHead { constructor(el) { this.audioCtx = new AudioContext(); this.opt={}; this.mtAvatar={}; el.textContent='Avatar'; } async showAvatar(){} lookAtCamera(){} start(){} stop(){} stopSpeaking(){} }`

for (const action of ['finish', 'mute'] as const) {
  test(`recorded speech ${action === 'finish' ? 'submits once' : 'is discarded when muted'}`, async ({ page }) => {
    const sent: any[] = [], uploads: number[] = []
    let socket: WebSocketRoute
    await page.addInitScript(() => { localStorage.setItem('aria_version', 'v2') })
    await page.route('**/avatar/live?*', r => r.fulfill({ contentType: 'text/html', body: html.replace('const SESSION =', 'params.set("avatar", "3d");\nconst SESSION =') }))
    await page.route('**/TalkingHead@*/modules/talkinghead.mjs', r => r.fulfill({ contentType: 'text/javascript', body: head }))
    await page.route('**/HeadAudio@*/**', r => r.abort())
    await page.route('**/api/chat/history?*', r => r.fulfill({ json: { history: [] } }))
    await page.route('**/api/voice/transcribe', async r => { uploads.push(1); await r.fulfill({ json: { text: 'Explain a bond' } }) })
    await page.routeWebSocket('**/api/live/ws', ws => { socket = ws; ws.onMessage(data => {
      const m = JSON.parse(String(data)); sent.push(m)
      if (m.type === 'user') socket.send(JSON.stringify({ type: 'done', turn: m.turn, text: 'A bond is a loan.' }))
    }) })
    await page.goto('/#/chat')
      await page.frameLocator('iframe[title="ARIA live avatar"]').getByRole('button', { name: 'Start conversation' }).click()
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await expect(page.locator('.meeting-status')).toHaveText('Listening to you…')
    await page.waitForTimeout(600) // enough time for the recorder to emit real data
    await page.getByRole('button', { name: action === 'finish' ? 'Finish speaking' : 'Mute microphone', exact: true }).click()
    if (action === 'finish') {
      await expect.poll(() => sent.filter(m => m.type === 'user').length).toBe(1)
      expect(sent.find(m => m.type === 'user').text).toBe('Explain a bond')
      expect(uploads).toHaveLength(1)
    } else {
      await page.waitForTimeout(1000)
      expect(uploads).toHaveLength(0)
      expect(sent.filter(m => m.type === 'user')).toHaveLength(0)
    }
  })
}
