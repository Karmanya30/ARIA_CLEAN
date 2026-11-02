import { test, expect } from '@playwright/test'

// Like two windows side by side: drag the divider and both panes follow.
test('the history panel and the avatar chat can be resized by dragging their edges', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('aria_owner_id', 'resize-' + Date.now()); localStorage.setItem('aria_version', 'v2') })
  await page.goto('/#/chat')
  await expect(page.getByRole('dialog', { name: 'ARIA Live meeting' })).toBeVisible()
  const box = (sel: string) => page.evaluate((s) => { const r = document.querySelector(s)!.getBoundingClientRect(); return { x: Math.round(r.x), w: Math.round(r.width), right: Math.round(r.right) } }, sel)

  // history panel: drag its right edge from 300 to 420
  await page.getByRole('button', { name: 'Chat history' }).click()
  await expect.poll(async () => (await box('#history-panel')).w).toBe(300)
  await page.waitForTimeout(500) // let the slide-in finish before measuring the divider
  const edge = await box('.history-resize')
  const y = 400
  await page.mouse.move(edge.x + edge.w / 2, y)
  await page.mouse.down()
  await page.mouse.move(420, y, { steps: 6 })
  await page.mouse.up()
  expect((await box('#history-panel')).w).toBe(420)
  expect((await box('.live-meeting')).x).toBe(420) // the avatar view moved with the divider
  // the width is remembered
  await page.reload()
  await page.getByRole('button', { name: 'Chat history' }).click()
  await expect.poll(async () => (await box('#history-panel')).w).toBe(420)
  await page.getByRole('button', { name: 'Close chat history' }).click()

  // avatar chat: open it, drag its left edge to the left to widen it
  await page.getByRole('button', { name: 'Toggle chat' }).click()
  await expect.poll(async () => (await box('.meeting-chat')).w).toBe(400)
  const stageBefore = (await box('.meeting-stage')).w
  await page.waitForTimeout(600)
  const handle = await box('.meeting-resize')
  await page.mouse.move(handle.x + 6, y)
  await page.mouse.down()
  await page.mouse.move(handle.x - 120, y, { steps: 6 })
  await page.mouse.up()
  expect((await box('.meeting-chat')).w).toBeGreaterThan(480)
  expect((await box('.meeting-stage')).w).toBeLessThan(stageBefore - 70) // the avatar shrank to make room
  // keyboard: arrow keys nudge the divider
  const w0 = (await box('.meeting-chat')).w
  await page.locator('.meeting-resize').focus()
  await page.keyboard.press('ArrowLeft')
  expect((await box('.meeting-chat')).w).toBe(w0 + 24)
})
