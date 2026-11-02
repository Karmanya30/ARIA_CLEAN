import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => { if (window === window.top) { localStorage.setItem('aria_version', 'v2'); localStorage.setItem('aria_adapt_tone', 'off') } })
})

test('skip link keeps the page, the title names the page, and an unknown route is rewritten', async ({ page }) => {
  await page.goto('/#/settings')
  await expect(page.getByRole('heading', { name: 'Settings', exact: true })).toBeVisible()
  await expect(page).toHaveTitle('Settings - ARIA')
  await page.keyboard.press('Tab')
  await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused() // the first stop, before the disclaimer strip
  await page.keyboard.press('Enter')
  await expect(page).toHaveURL(/#\/settings$/)
  await expect(page.locator('#main')).toBeFocused()
  await page.goto('/#/nonsense')
  await page.reload() // opening the address fresh, as a pasted link does
  await expect(page).not.toHaveURL(/nonsense/)
})

test('settings has no empty Appearance heading', async ({ page }) => {
  await page.goto('/#/settings')
  await expect(page.getByRole('heading', { name: 'Colour mode' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Appearance' })).toHaveCount(0)
})
