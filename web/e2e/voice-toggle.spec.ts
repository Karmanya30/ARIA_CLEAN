import { test, expect, type Page } from '@playwright/test'

// Full Chromium supports Windows media capture; the bundled headless shell does not.
test.use({ channel: 'chromium', permissions: ['microphone'], launchOptions: { args: ['--use-fake-device-for-media-stream'] } })

async function openConversation(page: Page, version: string) {
  await page.addInitScript(version => {
    localStorage.setItem('aria_version', version)
    localStorage.setItem('aria_adapt_tone', 'off')
    const streams: MediaStream[] = []
    const stats = { chunks: 0, requests: 0 }
    const getUserMedia = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices)
    const capture = async (constraints: MediaStreamConstraints) => {
      stats.requests++
      const stream = await getUserMedia(constraints)
      streams.push(stream)
      return stream
    }
    navigator.mediaDevices.getUserMedia = capture
    const NativeRecorder = window.MediaRecorder
    window.MediaRecorder = class extends NativeRecorder {
      constructor(...args: ConstructorParameters<typeof MediaRecorder>) {
        super(...args)
        this.addEventListener('dataavailable', event => { if (event.data.size) stats.chunks++ })
      }
    }
    Object.assign(window, { micTest: { streams, stats, capture } })
  }, version)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/#/chat')
  await page.getByRole('combobox', { name: 'Mode', exact: true }).selectOption('Conversational Mode')
  return errors
}

async function captured(page: Page) {
  await expect.poll(() => page.evaluate(() => (window as any).micTest.stats.chunks)).toBeGreaterThan(0)
}
async function released(page: Page) {
  await expect.poll(() => page.evaluate(() => (window as any).micTest.streams.every((stream: MediaStream) => stream.getTracks().every(track => track.readyState === 'ended')))).toBe(true)
}
async function listening(page: Page) {
  await expect.poll(() => page.evaluate(() => (window as any).micTest.streams.some((stream: MediaStream) => stream.getTracks().some(track => track.readyState === 'live')))).toBe(true)
}
function replyAudio() {
  const rate = 24000, audio = Buffer.alloc(44 + rate * 3 * 2)
  audio.write('RIFF'); audio.writeUInt32LE(audio.length - 8, 4); audio.write('WAVEfmt ', 8)
  audio.writeUInt32LE(16, 16); audio.writeUInt16LE(1, 20); audio.writeUInt16LE(1, 22)
  audio.writeUInt32LE(rate, 24); audio.writeUInt32LE(rate * 2, 28); audio.writeUInt16LE(2, 32); audio.writeUInt16LE(16, 34)
  audio.write('data', 36); audio.writeUInt32LE(audio.length - 44, 40)
  for (let i = 0; i < rate * 3; i++) audio.writeInt16LE(Math.round(Math.sin(2 * Math.PI * 440 * i / rate) * .2 * 32767), 44 + i * 2)
  return audio
}

for (const version of ['v1', 'v2']) {
  test(`${version}: conversational microphone toggles, automatically submits and plays the reply`, async ({ page }) => {
    const errors = await openConversation(page, version)
    let transcriptions = 0, messages = 0
    let answer!: () => void
    const waiting = new Promise<void>(resolve => { answer = resolve })
    await page.route('**/api/voice/transcribe', async route => {
      transcriptions++
      expect(route.request().headers()['content-type']).toContain('multipart/form-data')
      expect(route.request().postDataBuffer()!.length).toBeGreaterThan(200)
      await route.fulfill({ json: { text: 'Explain emergency savings' } })
    })
    await page.route('**/api/chat', async route => {
      messages++
      expect(route.request().postDataJSON()).toMatchObject({ query: 'Explain emergency savings', mode: 'Conversational Mode' })
      await waiting
      await route.fulfill({ json: { domain: 'general', response: 'Keep savings for unexpected expenses.', audio_token: 'toggle-reply' } })
    })
    await page.route('**/api/audio/toggle-reply', route => route.fulfill({ contentType: 'audio/wav', body: replyAudio() }))
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Stop listening', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await captured(page)
    await expect(page.locator('.voice-disk-status')).toHaveText('Listening…')
    await expect(page.getByRole('textbox', { name: 'Message ARIA', exact: true })).toBeDisabled()
    await expect(page.getByRole('button', { name: 'Send message', exact: true })).toBeDisabled()
    expect(transcriptions).toBe(0)
    expect(messages).toBe(0)
    await page.getByRole('button', { name: 'Stop listening', exact: true }).click()
    await released(page)
    await expect.poll(() => messages).toBe(1)
    const busy = page.getByRole('button', { name: 'Transcribing', exact: true })
    await expect(busy).toBeDisabled()
    await expect(page.locator('.voice-disk-status')).toHaveText('Preparing your reply…')
    await busy.evaluate((button: HTMLButtonElement) => button.click())
    expect(transcriptions).toBe(1)
    expect(messages).toBe(1)
    answer()
    await expect(page.getByText('Keep savings for unexpected expenses.', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Start listening', exact: true })).toBeEnabled()
    const disk = page.locator('.voice-disk-stage')
    await expect(disk).toHaveAttribute('data-playing', 'true')
    await expect.poll(async () => Number(await disk.getAttribute('data-rms'))).toBeGreaterThan(.05)
    // A new microphone click interrupts reply playback; clearing then releases that capture.
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await expect(disk).toHaveAttribute('data-playing', 'false')
    await listening(page)
    await page.getByRole('button', { name: /^Clear chat$/i }).click()
    await released(page)
    expect(transcriptions).toBe(1)
    expect(messages).toBe(1)
    expect(errors).toEqual([])
  })

  test(`${version}: microphone denial, empty transcription and mode exit do not send a question`, async ({ page }) => {
    const errors = await openConversation(page, version)
    let messages = 0, transcriptions = 0
    await page.route('**/api/chat', route => { messages++; return route.fulfill({ json: { domain: 'general', response: 'Unexpected' } }) })
    await page.route('**/api/voice/transcribe', route => { transcriptions++; return route.fulfill({ json: { text: '   ' } }) })
    await page.evaluate(() => { navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('Denied', 'NotAllowedError')) })
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Microphone access was denied')
    await page.evaluate(() => { navigator.mediaDevices.getUserMedia = (window as any).micTest.capture })
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await captured(page)
    await page.getByRole('button', { name: 'Stop listening', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Could not hear a question')
    await released(page)
    expect(transcriptions).toBe(1)
    expect(messages).toBe(0)
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await listening(page)
    await page.getByRole('combobox', { name: 'Mode', exact: true }).selectOption('Normal Mode')
    await released(page)
    expect(transcriptions).toBe(1)
    expect(messages).toBe(0)
    // Cancel a pending permission request, then release its late-granted real stream.
    await page.getByRole('combobox', { name: 'Mode', exact: true }).selectOption('Conversational Mode')
    await page.evaluate(() => {
      navigator.mediaDevices.getUserMedia = async constraints => {
        const stream = await (window as any).micTest.capture(constraints)
        return new Promise<MediaStream>(resolve => { Object.assign(window, { grantMicLater: () => resolve(stream) }) })
      }
    })
    await page.getByRole('button', { name: 'Start listening', exact: true }).click()
    await listening(page)
    await page.getByRole('button', { name: 'Stop listening', exact: true }).click()
    await page.evaluate(() => (window as any).grantMicLater())
    await released(page)
    await expect(page.getByRole('button', { name: 'Start listening', exact: true })).toBeEnabled()
    expect(transcriptions).toBe(1)
    expect(messages).toBe(0)
    await page.evaluate(() => { navigator.mediaDevices.getUserMedia = (window as any).micTest.capture })
    await page.getByRole('combobox', { name: 'Mode', exact: true }).selectOption('Normal Mode')
    await page.route('**/api/voice/transcribe', route => { transcriptions++; return route.fulfill({ json: { text: 'What is a budget?' } }) })
    const before = await page.evaluate(() => (window as any).micTest.stats.chunks)
    await page.getByRole('button', { name: 'Record voice message', exact: true }).click()
    await expect.poll(() => page.evaluate(() => (window as any).micTest.stats.chunks)).toBeGreaterThan(before)
    await page.getByRole('button', { name: 'Stop listening', exact: true }).click()
    await expect(page.getByRole('textbox', { name: 'Message ARIA', exact: true })).toHaveValue('What is a budget?')
    await released(page)
    expect(messages).toBe(0)
    expect(errors).toEqual([])
  })
}
