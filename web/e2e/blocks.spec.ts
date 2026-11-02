import { test, expect } from '@playwright/test'

// Structured blocks (metrics, risk, chart) are drawn under the written answer; the answer text is not repeated.
for (const ui of ['v1', 'v2']) {
  test(`${ui}: structured blocks render once under the answer`, async ({ page }) => {
    await page.addInitScript((u) => { for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined }); localStorage.setItem('aria_owner_id', 'blocks-' + Date.now()); localStorage.setItem('aria_version', u) }, ui)
    await page.route('**/api/chat', (route) => route.request().method() === 'POST' ? route.fulfill({ json: {
      domain: 'finance', query: 'sip', response: 'Your SIP plan is on track.',
      blocks: [
        { type: 'text', content: 'Your SIP plan is on track.' },
        { type: 'metric', label: 'Monthly SIP', value: '₹10,000' },
        { type: 'risk', level: 'Moderate', score: 0.8, factors: [{ name: 'Emergency fund', contribution: 0.3 }] },
      ] } }) : route.continue())
    await page.goto('/')
    await page.getByRole('button', { name: 'Leave meeting' }).click({ timeout: 8000 }).catch(() => {})
    await page.getByLabel('Message ARIA').fill('sip')
    await page.getByLabel('Message ARIA').press('Enter')
    await expect(page.getByText('₹10,000', { exact: true })).toBeVisible()
    await expect(page.getByText('Emergency fund')).toBeVisible()
    await expect(page.getByText('Your SIP plan is on track.')).toHaveCount(1)
  })
}
