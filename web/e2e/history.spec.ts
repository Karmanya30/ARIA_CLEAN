import { test, expect, type Browser, type Page } from '@playwright/test'

// Real backend, real browser. Two separate browser contexts stand in for two devices that share only the owner id.
const owner = `e2e-history-${Date.now()}`

async function leaveMeeting(page: Page) {
  // the app opens in the Live meeting; the chat history and sidebar are in the normal chat view
  await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
}

async function openHistory(page: Page) {
  if (!(await page.locator('.history-drawer.open').count())) await page.locator('.history-toggle').click()
}

async function closeHistory(page: Page) {
  if (await page.locator('.history-drawer.open').count()) await page.keyboard.press('Escape')
}

async function device(browser: Browser) {
  const ctx = await browser.newContext()
  await ctx.addInitScript(([o, ui]) => {
    localStorage.setItem('aria_version', ui) // which UI copy: ARIA_UI=v2 to run against the redesigned one
    for (const name of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, name, { value: undefined }) // never listen to the real microphone
    localStorage.setItem('aria_owner_id', o)
    localStorage.setItem('aria_mode', 'Normal Mode')
  }, [owner, process.env.ARIA_UI ?? 'v1'])
  return { ctx, page: await ctx.newPage() }
}

test.setTimeout(180_000)
test('a chat is saved, survives refresh, opens on a second device, and can be renamed, pinned and deleted', async ({ browser }) => {
  const a = await device(browser)
  const errors: string[] = []
  a.page.on('pageerror', (e) => errors.push(e.message))
  await a.page.goto('/')
  await leaveMeeting(a.page)
  // ask through the app's own API route so the answer does not depend on a language model
  await expect(a.page.locator('.history-toggle')).toBeVisible() // the app has started and chosen its session id
  const sid = await a.page.evaluate(() => localStorage.getItem('aria_session_id'))
  const res = await a.page.request.post('/api/chat', { data: { query: 'hello', session_id: sid, owner_id: owner, request_id: crypto.randomUUID() } })
  expect(res.ok(), `${res.status()} ${await res.text()}`).toBeTruthy()

  // refresh: the chat is in the history drawer and still the open one
  await a.page.reload()
  await leaveMeeting(a.page)
  await openHistory(a.page)
  const item = a.page.locator('.conv-item', { hasText: 'Hello' })
  await expect(item).toBeVisible()
  await expect(item).toHaveClass(/active/)

  // second device: nothing stored locally except the owner id, yet the chat is listed and opened
  const b = await device(browser)
  await b.page.goto('/')
  await leaveMeeting(b.page)
  await openHistory(b.page)
  await expect(b.page.locator('.conv-item', { hasText: 'Hello' })).toBeVisible()
  await expect(b.page.locator('.conv-item.active')).toHaveCount(1)
  await expect.poll(() => b.page.evaluate(() => localStorage.getItem('aria_session_id'))).toBe(sid)
  await closeHistory(b.page)
  await expect(b.page.locator('.bubble-user', { hasText: 'hello' })).toBeVisible()

  // rename from device A, visible on device B after a reload
  a.page.once('dialog', (d) => d.accept('Greeting test'))
  await item.hover()
  await item.getByRole('button', { name: 'Rename' }).click()
  await expect(a.page.locator('.conv-item', { hasText: 'Greeting test' })).toBeVisible()
  await b.page.reload()
  await leaveMeeting(b.page)
  await openHistory(b.page)
  await expect(b.page.locator('.conv-item', { hasText: 'Greeting test' })).toBeVisible()

  // search, pin
  await a.page.getByLabel('Search chats').fill('greeting')
  await expect(a.page.locator('.conv-item')).toHaveCount(1)
  await a.page.getByLabel('Search chats').fill('zzzz-no-such-chat')
  await expect(a.page.getByText('No chats match your search.')).toBeVisible()
  await a.page.getByLabel('Search chats').fill('')
  const pinRow = a.page.locator('.conv-item', { hasText: 'Greeting test' })
  await pinRow.hover()
  await pinRow.getByRole('button', { name: 'Pin' }).click()
  await expect(a.page.locator('.conv-group h3', { hasText: 'Pinned' })).toBeVisible()

  await closeHistory(a.page)
  // rate the answer on A; the rating is still there after a reload
  await a.page.getByRole('button', { name: 'Helpful' }).first().click()
  await a.page.reload()
  await leaveMeeting(a.page)
  await expect(a.page.getByRole('button', { name: 'Helpful' }).first()).toHaveAttribute('aria-pressed', 'true')

  // delete on A: gone from B as well
  await openHistory(a.page)
  a.page.once('dialog', (d) => d.accept())
  const row = a.page.locator('.conv-item', { hasText: 'Greeting test' })
  await row.hover()
  await row.getByRole('button', { name: 'Delete' }).click()
  await b.page.reload()
  await leaveMeeting(b.page)
  await openHistory(b.page)
  await expect(b.page.locator('.conv-item', { hasText: 'Greeting test' })).toHaveCount(0)
  expect(errors).toEqual([])
  await a.ctx.close(); await b.ctx.close()
})
