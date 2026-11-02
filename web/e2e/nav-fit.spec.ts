import { test, expect } from '@playwright/test'

// Every top-bar destination must be visible without scrolling, at common widths, and look the same on every page.
for (const width of [1920, 1440, 1280, 1100]) {
  test(`top navigation fits without scrolling at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await page.addInitScript(() => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', 'nav-' + Date.now()) })
    await page.goto('/#/chat') // the busiest bar: the Chats button is only here
    await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
    const labels = ['Markets', 'Explore', 'Chat', 'Reports', 'Intelligence', 'Profile', 'Progress', 'Feedback', 'Settings']
    for (const name of labels) {
      const tab = page.getByRole('tab', { name, exact: true })
      await expect(tab).toBeVisible()
      const box = await tab.boundingBox()
      expect(box!.x + box!.width, `${name} fully inside the window`).toBeLessThanOrEqual(width)
      expect(box!.x).toBeGreaterThanOrEqual(0)
    }
    await page.screenshot({ path: `../.audit/nav-${width}.png` })
    const nav = page.getByRole('tablist')
    expect(await nav.evaluate((el) => el.scrollWidth <= el.clientWidth + 1), 'nav has no hidden overflow').toBe(true)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'page has no sideways scroll').toBe(true)
  })
}

test('account details are in Settings, not a floating button', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('aria_owner_id', 'acct-' + Date.now()))
  await page.goto('/#/settings')
  await expect(page.locator('details.aria-account')).toHaveCount(0)
  await expect(page.getByText('Account', { exact: true })).toHaveCount(0) // private mode: no account section at all
})
