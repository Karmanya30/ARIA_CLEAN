import { test, expect } from '@playwright/test'

for (const version of ['v2']) {
  test(`${version}: feedback captures contact, discovery and bug details`, async ({ page }) => {
    let submitted: any = null
    await page.addInitScript(version => localStorage.setItem('aria_version', version), version)
    await page.route('**/api/feedback/status', r => r.fulfill({ json: { configured: true } }))
    await page.route('**/api/feedback', r => { submitted = r.request().postDataJSON(); return r.fulfill({ json: { sent: true } }) })
    await page.goto('/#/feedback')
    await expect(page.getByRole('heading', { name: 'Help shape ARIA' })).toBeVisible()
    await page.getByLabel('Your name').fill('Test User')
    await page.getByLabel('Email address').fill('test@example.test')
    await page.getByLabel('What would you like to share?').selectOption('Bug report')
    await page.getByLabel('How did you hear about ARIA?').selectOption('Other')
    await page.getByLabel('Please tell us where').fill('Campus showcase')
    await page.getByLabel('Your message').fill('The chart does not load when I select a date.')
    await page.getByRole('button', { name: 'Send feedback' }).click()
    await expect(page.getByRole('status')).toContainText('feedback has been sent')
    expect(submitted).toEqual({ name: 'Test User', email: 'test@example.test', category: 'Bug report', discovery: 'Campus showcase', message: 'The chart does not load when I select a date.' })
    await page.getByRole('button', { name: 'Send another response' }).click()
    await expect(page.getByLabel('Your name')).toHaveValue('')
  })
}

test('feedback stays visible but cannot claim delivery when email is unavailable', async ({ page }) => {
  await page.route('**/api/feedback/status', r => r.fulfill({ json: { configured: false } }))
  await page.goto('/#/feedback')
  await expect(page.getByRole('status')).toContainText('not configured')
  await expect(page.getByRole('button', { name: 'Send feedback' })).toBeDisabled()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
})

test('SMTP failure preserves the typed feedback', async ({ page }) => {
  await page.route('**/api/feedback/status', r => r.fulfill({ json: { configured: true } }))
  await page.route('**/api/feedback', r => r.fulfill({ status: 502, json: { detail: 'Email delivery failed. Please try again.' } }))
  await page.goto('/#/feedback')
  await page.getByLabel('Your name').fill('Test User')
  await page.getByLabel('Email address').fill('test@example.test')
  await page.getByLabel('How did you hear about ARIA?').selectOption('Friend or colleague')
  await page.getByLabel('Your message').fill('Please improve the charts.')
  await page.getByRole('button', { name: 'Send feedback' }).click()
  await expect(page.getByRole('alert')).toContainText('Email delivery failed')
  await expect(page.getByLabel('Your message')).toHaveValue('Please improve the charts.')
})

test('the disclaimer contact link opens feedback', async ({ page }) => {
  await page.route('**/api/feedback/status', r => r.fulfill({ json: { configured: false } }))
  await page.goto('/#/disclaimers')
  await page.getByRole('link', { name: 'feedback form' }).click()
  await expect(page.getByRole('heading', { name: 'Help shape ARIA' })).toBeVisible()
})
