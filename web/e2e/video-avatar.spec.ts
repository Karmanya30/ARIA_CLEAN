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
