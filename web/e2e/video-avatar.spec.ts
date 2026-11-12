import { test, expect, type Page } from '@playwright/test'

// "New ARIA Avatar" (video presenter) is a separate choice; the existing avatar stays the default.
async function kind(page: Page) {
  const el = page.locator('iframe[title="ARIA live avatar"]')
  await expect(el).toBeVisible()
  const cf = (await el.elementHandle().then((h) => h!.contentFrame()))!
  return { cf, kind: await cf.evaluate(() => (window as any).__ariaLive?.kind?.() ?? null).catch(() => null) } // the page may still be loading
}
const open = async (page: Page) => {
  await page.addInitScript(() => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', 'vid-' + Date.now()) })
  await page.goto('/#/chat')
}

test('the existing avatar is still the default', async ({ page }) => {
  await open(page)
  await expect(page.getByLabel('Avatar')).toHaveValue('classic')
  await expect.poll(async () => (await kind(page)).kind, { timeout: 60000 }).not.toBeNull()
  expect((await kind(page)).kind).not.toBe('video')
  await expect(page.locator('iframe[title="ARIA live avatar"]')).toHaveAttribute('src', /^((?!avatar=video).)*$/)
})

test('choosing New ARIA Avatar loads the video presenter on the old avatar scene, held steady, and remembers the choice', async ({ page }) => {
  await open(page)
  await page.getByLabel('Avatar').selectOption('new')
  await expect(page.locator('iframe[title="ARIA live avatar"]')).toHaveAttribute('src', /avatar=video/)
  await expect.poll(async () => (await kind(page)).kind, { timeout: 25000 }).toBe('video')
  const { cf } = await kind(page)
  await page.waitForTimeout(1200)
  const held = await cf.evaluate(() => { const v = document.querySelector('video') as HTMLVideoElement; return { paused: v.paused, t: v.currentTime, w: v.videoWidth, h: v.videoHeight } })
  expect(held.paused, 'the idle picture is held, not looping').toBe(true)
  expect(held.t, 'the held frame: eyes open, calm smile').toBeCloseTo(0.72, 1)
  expect([held.w, held.h], 'the whole old-avatar scene, in the old photo proportions (not a face crop)').toEqual([1440, 616])
  await page.reload()
  await expect(page.getByLabel('Avatar')).toHaveValue('new')
})

test('New ARIA Avatar is attentive only while the client speaks, and stable otherwise (including while ARIA talks without the GPU server)', async ({ page }) => {
  test.setTimeout(120000)
  await open(page)
  await page.getByLabel('Avatar').selectOption('new')
  await expect.poll(async () => (await kind(page)).kind, { timeout: 40000 }).toBe('video')
  const { cf } = await kind(page)
  const clip = () => cf.evaluate(() => (window as any).__ariaLive.speaker().current())
  expect(await clip()).toBe('idle')
  // the idle picture is a held frame, not a moving loop
  expect(await cf.evaluate(() => (document.querySelector('video') as HTMLVideoElement).paused)).toBe(true)
  // a note explains how to get lip-sync when the GPU server is not running
  await expect(cf.locator('#note')).toContainText('lip-sync GPU is not available right now')
  // ARIA speaking without lip-sync keeps the stable face (no unrelated mouth or head movement)
  await cf.evaluate(async () => {
    const sp = (window as any).__ariaLive.speaker()
    await sp.ctx.resume()
    const buf = sp.ctx.createBuffer(1, sp.ctx.sampleRate * 3, sp.ctx.sampleRate)
    const d = buf.getChannelData(0)
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (i < 8000 ? 0.7 : 0.2)
    sp.play(buf, 'test voice')
  })
  for (let i = 0; i < 4; i++) { expect(await clip()).toBe('idle'); await page.waitForTimeout(600) }
  // while the client speaks she listens attentively, then settles again
  await cf.evaluate(() => { (window as any).__forceUserSpeaking = true })
  await expect.poll(clip, { timeout: 4000 }).toBe('listen')
  await cf.evaluate(() => { (window as any).__forceUserSpeaking = false })
  await expect.poll(clip, { timeout: 5000 }).toBe('idle')
})
