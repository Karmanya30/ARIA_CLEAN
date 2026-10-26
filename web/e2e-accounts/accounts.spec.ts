import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'

const password = 'synthetic-browser-password-123'
const errors = new WeakMap<Page, string[]>()
test.beforeEach(async ({ page }) => {
  const messages: string[] = []
  errors.set(page, messages)
  page.on('pageerror', error => messages.push(error.message))
})
test.afterEach(async ({ page }, info) => {
  await info.attach('page-errors', { body: JSON.stringify(errors.get(page)), contentType: 'application/json' })
  expect(errors.get(page)).toEqual([])
})

async function googleAdapter(page: Page, email: string) {
  await page.route('https://accounts.google.com/gsi/client', route => route.fulfill({ contentType: 'application/javascript', body: `
    window.google = { accounts: { id: {
      initialize(options) { this.options = options; },
      renderButton(element) {
        const options = this.options;
        const button = document.createElement('button');
        button.textContent = 'Synthetic Google sign-in';
        button.onclick = () => options.callback({credential: JSON.stringify({
          aud: options.client_id, nonce: options.nonce, iss: 'https://accounts.google.com',
          sub: ${JSON.stringify('synthetic-sub-' + email)}, email: ${JSON.stringify(email)},
          email_verified: true, exp: Math.floor(Date.now()/1000)+300
        })});
        element.appendChild(button);
      }
    }}};` }))
}
async function start(page: Page, version: string, email: string) {
  await googleAdapter(page, email)
  await page.addInitScript(version => {
    if (window !== window.top) return // Sandboxed report documents intentionally cannot use storage.
    localStorage.setItem('aria_version', version)
    localStorage.setItem('aria_owner_id', 'synthetic-legacy-private-owner')
  }, version)
  await page.goto('/#/profile')
  await expect(page.getByRole('heading', { name: 'Sign in to ARIA' })).toBeVisible()
}
async function credentials(page: Page, email: string, signup = false) {
  if (signup) await page.getByRole('button', { name: 'Create an account', exact: true }).click()
  await page.getByLabel('Email', { exact: true }).fill(email)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: signup ? 'Create account' : 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Your Finance Profile' })).toBeVisible()
}
function persisted(owner: string) {
  const db = path.resolve('..', '.audit', 'browser', process.env.ARIA_AUDIT_RUN!, 'aria.db')
  const code = 'import sqlite3,sys,json; c=sqlite3.connect(sys.argv[1]); print(json.dumps(c.execute("select monthly_income,age from financial_profiles where user_id=?",(sys.argv[2],)).fetchone()))'
  return JSON.parse(execFileSync(path.resolve('..', '.venv', 'Scripts', 'python.exe'), ['-c', code, db, owner], { encoding: 'utf8' }))
}

for (const version of ['v1', 'v2']) {
  test(`${version}: email account persists profile across logout, new browser session and account change`, async ({ page, browser }) => {
    const email = `${crypto.randomUUID()}@example.test`
    await start(page, version, email)
    await credentials(page, email, true)
    const user = (await (await page.request.get('/api/auth/session')).json()).user
    await page.getByLabel('Age', { exact: true }).fill('35')
    await page.getByLabel('City', { exact: true }).fill('Synthetic City')
    await page.getByRole('button', { name: 'Save & next' }).click()
    await page.getByLabel('Monthly take-home income').fill('91000')
    await page.getByRole('button', { name: 'Save & next' }).click()
    await expect.poll(() => persisted(user.id)).toEqual([91000, 35])
    expect(await page.evaluate(() => localStorage.getItem('aria_owner_id'))).toBe('synthetic-legacy-private-owner')
    await page.getByRole('tab', { name: 'Settings', exact: true }).click()
    await page.getByRole('tab', { name: 'Your Profile', exact: true }).click()
    await page.reload()
    await expect(page.getByLabel('Age', { exact: true })).toHaveValue('35')
    const anotherTab = await page.context().newPage()
    await googleAdapter(anotherTab, email)
    await anotherTab.goto('/#/profile')
    await expect(anotherTab.getByLabel('Age', { exact: true })).toHaveValue('35')
    await page.locator('summary').filter({ hasText: /^Account$/ }).click()
    await page.getByRole('button', { name: 'Sign out', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Sign in to ARIA' })).toBeVisible()
    await expect(anotherTab.getByRole('heading', { name: 'Sign in to ARIA' })).toBeVisible()
    await anotherTab.close()
    const fresh = await browser.newContext()
    const login = await fresh.newPage()
    await start(login, version, email)
    await credentials(login, email)
    await expect(login.getByLabel('Age', { exact: true })).toHaveValue('35')
    expect(persisted(user.id)).toEqual([91000, 35])
    await credentials(page, `${crypto.randomUUID()}@example.test`, true)
    await expect(page.getByLabel('Age', { exact: true })).toHaveValue('')
    expect((await page.request.get(`/api/profile?session_id=${user.id}`)).status()).toBe(403)
    await fresh.close()
  })
}

test('Google account signs in through the browser adapter and survives refresh', async ({ page }) => {
  const email = `${crypto.randomUUID()}@gmail.com`
  await start(page, 'v1', email)
  await page.getByRole('button', { name: 'Synthetic Google sign-in' }).click()
  await expect(page.getByRole('heading', { name: 'Your Finance Profile' })).toBeVisible()
  const first = (await (await page.request.get('/api/auth/session')).json()).user
  expect(first.email).toBe(email)
  await page.getByRole('tab', { name: 'Chat', exact: true }).click()
  await page.getByLabel('Message ARIA', { exact: true }).fill('equity research report on TESTCO')
  const generated = page.waitForResponse(response => response.url().endsWith('/api/chat') && response.request().method() === 'POST')
  await page.getByRole('button', { name: 'Send message' }).click()
  expect((await generated).ok()).toBeTruthy()
  await page.getByRole('tab', { name: 'Research reports', exact: true }).click()
  await expect(page.frameLocator('iframe[title="Equity research report"]').locator('body')).toContainText('Test')
  const downloaded = page.waitForEvent('download')
  await page.getByTitle('Download HTML', { exact: true }).click()
  expect(await (await downloaded).failure()).toBeNull()
  await page.getByRole('tab', { name: 'Your Profile', exact: true }).click()
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Your Finance Profile' })).toBeVisible()
  expect((await (await page.request.get('/api/auth/session')).json()).user.id).toBe(first.id)
})

test('Password account explicitly links Google and can use either sign-in method', async ({ page }) => {
  const email = `${crypto.randomUUID()}@gmail.com`
  await start(page, 'v2', email)
  await credentials(page, email, true)
  const user = (await (await page.request.get('/api/auth/session')).json()).user
  await page.locator('summary').filter({ hasText: /^Account$/ }).click()
  await page.getByRole('button', { name: 'Synthetic Google sign-in' }).click()
  await expect(page.locator('.aria-account').getByRole('status')).toHaveText('Google account connected.')
  await page.getByRole('button', { name: 'Sign out', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Sign in to ARIA' })).toBeVisible()
  await page.getByRole('button', { name: 'Synthetic Google sign-in' }).click()
  await expect(page.getByRole('heading', { name: 'Your Finance Profile' })).toBeVisible()
  expect((await (await page.request.get('/api/auth/session')).json()).user.id).toBe(user.id)
})
