import { test, expect } from '@playwright/test'

// The live meeting is a modal that makes the rest of the page inert; the history panel must stay clickable inside it.
test('inside the live meeting the history panel opens, can be closed with its X, and its chats can be clicked', async ({ page }) => {
  await page.addInitScript(() => { localStorage.setItem('aria_owner_id', 'meeting-history-' + Date.now()); localStorage.setItem('aria_version', 'v2') })
  await page.goto('/#/chat')
  await expect(page.getByRole('dialog', { name: 'ARIA Live meeting' })).toBeVisible()
  await page.getByRole('button', { name: 'Chat history' }).click()
  await expect(page.locator('.history-panel.open')).toBeVisible()
  await page.getByRole('button', { name: 'Close chat history' }).click()
  await expect(page.locator('.history-panel.open')).toHaveCount(0)
  await page.getByRole('button', { name: 'Chat history' }).click()
  await page.getByLabel('Search chats').fill('anything')
  await expect(page.getByLabel('Search chats')).toHaveValue('anything')
})
