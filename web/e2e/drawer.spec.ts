import { test, expect } from '@playwright/test'

test('history is a left panel on the Chat page only, and lists chats from every mode', async ({ page }) => {
  const owner = 'drawer-' + Date.now()
  await page.addInitScript((o) => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', o); localStorage.setItem('aria_version', 'v2') }, owner)
  await page.goto('/#/chat')
  await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
  const sid = await page.evaluate(() => localStorage.getItem('aria_session_id'))
  await page.request.post('/api/chat', { data: { query: 'You are a market news analyst. 1. x User question: when was this result out?', session_id: sid, owner_id: owner, request_id: crypto.randomUUID() } })
  await page.reload()
  await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
  // closed by default: no list on the page
  await expect(page.locator('.history-button')).toBeVisible()
  await expect(page.getByLabel('Search chats')).toBeHidden()
  await page.locator('.history-button').click()
  await expect(page.locator('.history-panel.open .conv-item', { hasText: 'When was this result out' })).toBeVisible()
  // the page moves over instead of being covered
  await expect.poll(() => page.evaluate(() => document.body.classList.contains('history-open'))).toBe(true)
  // opening a chat asks how to continue: chat, voice or video call
  await page.locator('.history-panel.open .conv-item', { hasText: 'When was this result out' }).locator('.conv-open').click()
  const ask = page.getByRole('dialog', { name: 'How do you want to continue?' })
  await expect(ask.getByRole('button', { name: /^Chat/ })).toBeVisible()
  await expect(ask.getByRole('button', { name: /^Voice/ })).toBeVisible()
  await ask.getByRole('button', { name: /^Video call/ }).click()
  // video call = the live meeting; its own Chats button opens the same panel and the stage moves over
  await expect(page.getByRole('dialog', { name: 'ARIA Live meeting' })).toBeVisible()
  await expect.poll(() => page.evaluate(() => getComputedStyle(document.querySelector('.live-meeting')!).left)).toBe('300px')
  await page.getByRole('button', { name: 'Leave meeting' }).click()
  await page.keyboard.press('Escape')
  await expect(page.locator('.history-panel.open')).toHaveCount(0)
  // not on other pages
  await page.getByRole('tab', { name: /Explore/ }).click().catch(async () => { await page.getByText('Explore', { exact: true }).first().click() })
  await expect(page.locator('.history-button')).toHaveCount(0)
  await expect(page.locator('.conv-list')).toHaveCount(0)
})
