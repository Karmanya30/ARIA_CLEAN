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

test('choosing New ARIA Avatar loads the video presenter, plays it, and remembers the choice', async ({ page }) => {
  await open(page)
  await page.getByLabel('Avatar').selectOption('new')
  await expect(page.locator('iframe[title="ARIA live avatar"]')).toHaveAttribute('src', /avatar=video/)
  await expect.poll(async () => (await kind(page)).kind, { timeout: 25000 }).toBe('video')
  const { cf } = await kind(page)
  const t0 = await cf.evaluate(() => (document.querySelector('video') as HTMLVideoElement).currentTime)
  await page.waitForTimeout(1500)
  expect(await cf.evaluate(() => (document.querySelector('video') as HTMLVideoElement).currentTime), 'the calm loop is playing').toBeGreaterThan(t0)
  await page.reload()
  await expect(page.getByLabel('Avatar')).toHaveValue('new')
})

test('New ARIA Avatar switches to a talking clip while a voice plays and back to the calm loop after', async ({ page }) => {
  await open(page)
  await page.getByLabel('Avatar').selectOption('new')
  await expect.poll(async () => (await kind(page)).kind, { timeout: 40000 }).toBe('video')
  const { cf } = await kind(page)
  expect(await cf.evaluate(() => (window as any).__ariaLive.speaker().current())).toMatch(/idle|smile|tilt|greet/)
  // a synthetic 3 s voice: noise with a loud start so the emphasis rule can fire
  await cf.evaluate(async () => {
    const sp = (window as any).__ariaLive.speaker()
    await sp.ctx.resume()
    const buf = sp.ctx.createBuffer(1, sp.ctx.sampleRate * 3, sp.ctx.sampleRate)
    const d = buf.getChannelData(0)
    for (let i = 0; i < d.length; i++) d[i] = (Math.random() * 2 - 1) * (i < 8000 ? 0.7 : 0.2)
    sp.play(buf, 'test voice')
  })
  await expect.poll(() => cf.evaluate(() => (window as any).__ariaLive.speaker().current()), { timeout: 5000 }).toMatch(/^talk[123]$/)
  await expect.poll(() => cf.evaluate(() => (window as any).__ariaLive.speaker().current()), { timeout: 9000 }).toMatch(/idle|smile|tilt|greet/)
})
