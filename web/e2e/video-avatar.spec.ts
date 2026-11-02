import { test, expect } from '@playwright/test'

// The live meeting uses the video presenter when no GPU lip-sync server is running.
test('the live avatar is the video presenter and it is playing', async ({ page }) => {
  await page.addInitScript(() => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', 'vid-' + Date.now()) })
  await page.goto('/#/chat')
  const frameEl = page.locator('iframe[title="ARIA live avatar"]')
  await expect(frameEl).toBeVisible()
  const frame = page.frameLocator('iframe[title="ARIA live avatar"]')
  await expect(frame.locator('video')).toHaveCount(2, { timeout: 20000 })
  await expect.poll(async () => (await frameEl.elementHandle().then((h) => h!.contentFrame()))!.evaluate(() => (window as any).__ariaLive.kind()), { timeout: 20000 }).toBe('video')
  const cf = (await frameEl.elementHandle().then((h) => h!.contentFrame()))!
  const t0 = await cf.evaluate(() => (document.querySelector('video') as HTMLVideoElement).currentTime)
  await page.waitForTimeout(1500)
  const t1 = await cf.evaluate(() => (document.querySelector('video') as HTMLVideoElement).currentTime)
  expect(t1, 'the calm loop is playing').toBeGreaterThan(t0)
  await page.screenshot({ path: '../.audit/video-avatar.png' })
})
