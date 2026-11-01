import { test, expect } from '@playwright/test'

test('history is a drawer on the Chat page only, and lists chats from every mode', async ({ page }) => {
  const owner = 'drawer-' + Date.now()
  await page.addInitScript((o) => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', o); localStorage.setItem('aria_version', 'v2') }, owner)
  await page.goto('/')
  await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
  const sid = await page.evaluate(() => localStorage.getItem('aria_session_id'))
  await page.request.post('/api/chat', { data: { query: 'You are a market news analyst. 1. x User question: when was this result out?', session_id: sid, owner_id: owner, request_id: crypto.randomUUID() } })
  await page.reload()
  await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
  // closed by default: no list on the page
  await expect(page.locator('.history-toggle')).toBeVisible()
  await expect(page.getByLabel('Search chats')).toBeHidden()
  await page.locator('.history-toggle').click()
  await expect(page.locator('.history-drawer.open .conv-item', { hasText: 'When was this result out' })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.locator('.history-drawer.open')).toHaveCount(0)
  // not on other pages
  await page.getByRole('tab', { name: /Explore/ }).click().catch(async () => { await page.getByText('Explore', { exact: true }).first().click() })
  await expect(page.locator('.history-toggle')).toHaveCount(0)
  await expect(page.locator('.conv-list')).toHaveCount(0)
})
