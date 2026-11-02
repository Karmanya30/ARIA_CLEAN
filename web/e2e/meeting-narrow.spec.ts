import { test, expect } from '@playwright/test'

// UX-01: the live meeting header used to be ~760 px wide: Chats and Leave went off-screen and the meeting scrolled sideways.
for (const width of [390, 480, 600, 768, 1024]) {
  test(`live meeting header fits at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await page.addInitScript(() => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', 'narrow-' + Date.now()) })
    await page.goto('/#/chat')
    await expect(page.getByRole('dialog', { name: 'ARIA Live meeting' })).toBeVisible()
    for (const target of [page.getByRole('button', { name: 'Chat history' }), page.getByRole('button', { name: 'Leave meeting' }), page.getByLabel('Avatar')]) {
      const box = await target.boundingBox()
      expect(box, 'visible').not.toBeNull()
      expect(box!.x).toBeGreaterThanOrEqual(0)
      expect(box!.x + box!.width).toBeLessThanOrEqual(width + 0.5)
    }
    const m = await page.locator('.meeting-header').evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth }))
    expect(m.sw, 'the header content fits its row').toBeLessThanOrEqual(m.cw + 1)
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1), 'the page does not scroll sideways').toBe(true)
    // the chat panel fits too
    await page.getByRole('button', { name: 'Toggle chat' }).click()
    await page.waitForTimeout(500)
    const chat = await page.locator('.meeting-chat').boundingBox()
    expect(chat!.x).toBeGreaterThanOrEqual(-1)
    expect(chat!.x + chat!.width).toBeLessThanOrEqual(width + 1)
  })
}
