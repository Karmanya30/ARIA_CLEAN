import { test, expect, type Page } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import path from 'node:path'

const diagnostics = new WeakMap<Page, { errors: string[], failedRequests: string[] }>()
test.beforeEach(async ({ page }) => {
  const data = { errors: [] as string[], failedRequests: [] as string[] }
  diagnostics.set(page, data)
  page.on('pageerror', e => data.errors.push(e.message))
  page.on('requestfailed', r => data.failedRequests.push(`${r.method()} ${r.url()} ${r.failure()?.errorText}`))
})
test.afterEach(async ({ page }, info) => {
  await info.attach('browser-diagnostics', { body: JSON.stringify(diagnostics.get(page), null, 2), contentType: 'application/json' })
  expect(diagnostics.get(page)?.errors).toEqual([])
})

async function start(page: Page, version: string) {
  await page.addInitScript(({ version }) => {
    if (window !== window.top) return // Report iframes intentionally have no storage access.
    if (!localStorage.getItem('aria_version')) localStorage.setItem('aria_version', version)
    if (!localStorage.getItem('aria_adapt_tone')) localStorage.setItem('aria_adapt_tone', 'off')
  }, { version })
  await page.goto('/#/profile')
  await expect(page.getByRole('heading', { name: 'Your Finance Profile' })).toBeVisible()
}
async function owner(page: Page) { return page.evaluate(() => localStorage.getItem('aria_owner_id')!) }
function stored(owner: string) {
  const db = path.resolve('..', '.audit', 'browser', process.env.ARIA_AUDIT_RUN!, 'aria.db')
  const query = 'import sqlite3,sys,json; c=sqlite3.connect(sys.argv[1]); r=c.execute("select monthly_income,age,details_json from financial_profiles where user_id=?",(sys.argv[2],)).fetchone(); print(json.dumps(r))'
  return JSON.parse(execFileSync(path.resolve('..', '.venv', 'Scripts', 'python.exe'), ['-c', query, db, owner], { encoding: 'utf8' }))
}

for (const version of ['v1', 'v2']) {
  test(`${version}: company analysis, sentiment control, progress and profile load retry`, async ({ page }) => {
    await start(page, version)
    await page.getByRole('tab', { name: 'Company intelligence', exact: true }).click()
    await page.getByLabel('Company', { exact: true }).fill('TESTCO')
    await page.getByRole('button', { name: 'Analyse', exact: true }).click()
    await expect(page.getByRole('button', { name: /New search/ })).toBeVisible()
    await page.getByRole('button', { name: /New search/ }).click()
    await expect(page.getByLabel('Company', { exact: true })).toHaveValue('')
    await page.getByText('Check the tone of any text', { exact: true }).click()
    await page.getByLabel('Texts to score', { exact: true }).fill('Synthetic growth and profits increased.')
    const sentimentResponse = page.waitForResponse(r => r.url().endsWith('/api/research/sentiment'))
    await page.getByRole('button', { name: 'Score text', exact: true }).click()
    expect((await (await sentimentResponse).json()).items).toHaveLength(1)
    await expect(page.getByRole('button', { name: 'Score text', exact: true })).toBeEnabled()
    const sid = await page.evaluate(() => localStorage.getItem('aria_session_id'))
    const answer = await page.request.post('/api/quiz/answer', { data: { session_id: sid, concept_id: 'sip', is_correct: true } })
    expect(answer.ok()).toBeTruthy()
    await page.getByRole('tab', { name: 'Your Progress', exact: true }).click()
    await expect(page.locator('.progress-list')).toBeVisible()
    await page.reload()
    await expect(page.locator('.progress-list')).toBeVisible()
    await page.route('**/api/profile?*', route => route.fulfill({ status: 503, json: { detail: 'Synthetic profile outage' } }))
    await page.getByRole('tab', { name: 'Your Profile', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Synthetic profile outage')
    await page.unroute('**/api/profile?*')
    await page.getByRole('button', { name: 'Try again', exact: true }).click()
    await expect(page.getByRole('region', { name: 'Quick form' })).toBeVisible()
  })

  test(`${version}: settings persist, markets renders, UI version switches`, async ({ page }) => {
    await start(page, version)
    await page.getByRole('tab', { name: 'Settings', exact: true }).click()
    await page.getByRole('checkbox', { name: 'Adapt tone to how I feel' }).check()
    await page.locator('label').filter({ has: page.locator('input[name=theme][value=vitara-markets]') }).click()
    await page.reload()
    await expect(page.locator('input[name=theme][value=vitara-markets]')).toBeChecked()
    await expect(page.getByRole('checkbox', { name: 'Adapt tone to how I feel' })).toBeChecked()
    await page.getByRole('tab', { name: 'Markets', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Markets', exact: true })).toBeVisible()
    await expect(page.getByRole('list', { name: 'Indices and benchmarks' })).toContainText('Nifty 50')
    await page.getByRole('tab', { name: 'Settings', exact: true }).click()
    const next = version === 'v1' ? 'v2' : 'v1'
    const switched = page.waitForEvent('load')
    await page.locator('label').filter({ has: page.locator(`input[name=app-version][value=${next}]`) }).click()
    await switched
    expect(await page.evaluate(() => localStorage.getItem('aria_version'))).toBe(next)
    await expect(page.locator(`input[name=app-version][value=${next}]`)).toBeChecked()
  })

  test(`${version}: chat history, acknowledgement, report generation, exports and version deletion`, async ({ page }) => {
    await start(page, version)
    let revealOnboarding!: () => void
    const gate = new Promise<void>(resolve => { revealOnboarding = resolve })
    await page.route('**/api/profile?*', async route => { await gate; await route.continue() })
    await page.getByRole('tab', { name: 'Chat', exact: true }).click()
    await page.getByLabel('Message ARIA', { exact: true }).focus()
    revealOnboarding()
    await expect(page.locator('#onb-income')).toBeVisible()
    await expect(page.getByLabel('Message ARIA', { exact: true })).toBeFocused()
    await page.unroute('**/api/profile?*')
    const send = async (query: string) => {
      await page.getByLabel('Message ARIA', { exact: true }).fill(query)
      const response = page.waitForResponse(r => r.url().endsWith('/api/chat') && r.request().method() === 'POST')
      await page.getByRole('button', { name: 'Send message' }).click()
      const result = await response
      expect(result.ok()).toBeTruthy()
      return result.json()
    }
    await send('hello')
    await send('ok')
    await page.reload()
    const id = await owner(page)
    const sid = await page.evaluate(() => localStorage.getItem('aria_session_id'))
    expect((await (await page.request.get(`/api/chat/history?session_id=${sid}&owner_id=${id}`)).json()).history).toHaveLength(2)
    const report = await send('equity research report on TESTCO')
    expect(report.report_id).toBeTruthy()
    await page.getByRole('tab', { name: 'Research reports', exact: true }).click()
    await expect(page.locator('iframe[title="Equity research report"]')).toBeVisible()
    await expect(page.frameLocator('iframe[title="Equity research report"]').locator('body')).toContainText('Test')
    for (const title of ['Download HTML', 'Download Markdown', 'Download all data (JSON)']) {
      const downloaded = page.waitForEvent('download')
      await page.getByTitle(title, { exact: true }).click()
      const file = await downloaded
      expect(await file.failure()).toBeNull()
    }
    await page.getByTitle('Regenerate on fresh data (new version)', { exact: true }).click()
    await expect(page.locator('.rt-ver').first()).toHaveText('v2')
    const reports = await (await page.request.get(`/api/research/reports?owner_id=${id}`)).json()
    expect(reports).toHaveLength(2)
    expect((await page.request.get(`/api/research/reports/${report.report_id}?owner_id=stranger`)).status()).toBe(404)
    page.once('dialog', d => d.dismiss())
    await page.getByTitle('Delete this version', { exact: true }).click()
    expect(await (await page.request.get(`/api/research/reports?owner_id=${id}`)).json()).toHaveLength(2)
    page.once('dialog', d => d.accept())
    await page.getByTitle('Delete this version', { exact: true }).click()
    await expect.poll(async () => (await (await page.request.get(`/api/research/reports?owner_id=${id}`)).json()).length).toBe(1)
    await page.getByRole('tab', { name: 'Chat', exact: true }).click()
    await page.getByRole('button', { name: /^Clear chat$/i }).click()
    await expect.poll(async () => (await (await page.request.get(`/api/chat/history?session_id=${sid}&owner_id=${id}`)).json()).history.length).toBe(0)
  })

  test(`${version}: explore drawer, chart range, watchlist persistence and close`, async ({ page }) => {
    await start(page, version)
    await page.getByRole('tab', { name: 'Explore', exact: true }).click()
    await page.locator('.ix-row').filter({ hasText: 'Reliance' }).first().click()
    await expect(page.getByRole('dialog')).toBeVisible()
    await page.getByRole('button', { name: 'Max', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Max', exact: true })).toHaveAttribute('aria-pressed', 'true')
    await page.getByRole('button', { name: /Add to watchlist/ }).click()
    await page.getByRole('button', { name: 'Close details', exact: true }).click()
    await expect(page.getByRole('dialog')).not.toBeVisible()
    await page.reload()
    await expect(page.getByRole('region', { name: 'Your watchlist', exact: true })).toContainText('Reliance')
    await page.getByRole('button', { name: /Remove .* from watchlist/ }).click()
    await expect(page.getByRole('region', { name: 'Your watchlist', exact: true }).locator('li')).toHaveCount(0)
  })

  test(`${version}: transaction server failure is visible and retry preserves input`, async ({ page }) => {
    await start(page, version)
    await page.getByLabel('Amount (₹)', { exact: true }).fill('200')
    await page.getByLabel('Merchant (optional)').fill('Retry merchant')
    await page.route('**/api/transactions', async route => {
      if (route.request().method() === 'POST') await route.fulfill({ status: 503, json: { detail: 'Synthetic service unavailable' } })
      else await route.continue()
    })
    await page.getByRole('button', { name: 'Add transaction', exact: true }).click()
    await expect(page.getByRole('alert')).toContainText('Synthetic service unavailable')
    await expect(page.getByLabel('Merchant (optional)')).toHaveValue('Retry merchant')
    await page.unroute('**/api/transactions')
    await page.getByRole('button', { name: 'Add transaction', exact: true }).click()
    await expect(page.locator('table').getByText('Retry merchant')).toBeVisible()
  })

  test(`${version}: profile persists through navigation, refresh, new chat and browser session`, async ({ page, browser }) => {
    await start(page, version)
    await page.getByLabel('Age', { exact: true }).fill('32')
    await page.getByLabel('City', { exact: true }).fill('Audit City')
    await page.getByRole('button', { name: 'Save & next' }).click()
    await page.getByLabel('Monthly take-home income').fill('125000')
    await page.getByLabel('Rent', { exact: true }).fill('25000')
    await page.getByLabel('Food', { exact: true }).fill('5000')
    await page.getByRole('button', { name: 'Save & next' }).click()
    const id = await owner(page)
    expect(stored(id).slice(0, 2)).toEqual([125000, 32])
    expect(JSON.parse(stored(id)[2]).expenses.rent).toBe(25000)
    await page.getByRole('button', { name: '2 Income & expenses', exact: true }).click()
    await page.getByLabel('Rent', { exact: true }).fill('')
    await page.getByRole('button', { name: 'Save & next' }).click()
    await expect.poll(() => JSON.parse(stored(id)[2]).expenses?.rent ?? null).toBeNull()
    expect(JSON.parse(stored(id)[2]).expenses.food).toBe(5000)
    await page.getByRole('tab', { name: 'Settings', exact: true }).click()
    await page.goBack()
    await page.reload()
    await expect(page.getByLabel('Age', { exact: true })).toHaveValue('32')
    await page.getByRole('button', { name: /New (session|chat)/ }).click()
    await page.getByRole('tab', { name: /Your Profile|^Profile$/ }).click()
    await expect(page.getByLabel('Age', { exact: true })).toHaveValue('32')
    const storageState = await page.context().storageState()
    const fresh = await browser.newContext({ storageState })
    const second = await fresh.newPage()
    await second.goto('/#/profile')
    await expect(second.getByLabel('Age', { exact: true })).toHaveValue('32')
    expect(stored(id)[0]).toBe(125000)
    const stranger = await browser.newContext()
    const other = await stranger.newPage()
    await other.goto('/#/profile')
    await expect(other.getByLabel('Age', { exact: true })).toHaveValue('')
    await fresh.close(); await stranger.close()
  })

  test(`${version}: transactions add, statement import, deduplication and clear`, async ({ page }) => {
    await start(page, version)
    await page.getByLabel('Amount (₹)', { exact: true }).fill('567')
    await page.getByLabel('Merchant (optional)').fill('Audit Grocer')
    await page.getByRole('button', { name: 'Add transaction', exact: true }).click()
    await expect(page.locator('table').getByText('Audit Grocer')).toBeVisible()
    await page.reload()
    await expect(page.locator('table').getByText('Audit Grocer')).toBeVisible()
    const id = await owner(page)
    const rows = await (await page.request.get(`/api/transactions?session_id=${id}`)).json()
    expect(rows).toHaveLength(1)
    expect(rows[0].amount).toBe(567)
    const statement = Buffer.from('Txn Date,Description,Amount\n2026-10-01,Zomato audit,-250.50\n2026-10-02,Payroll,50000\n')
    const previewReady = page.waitForResponse(r => r.url().endsWith('/api/transactions/parse'))
    await page.locator('input[type=file]').setInputFiles({ name: 'synthetic.csv', mimeType: 'text/csv', buffer: statement })
    const parsedPreview = await (await previewReady).json()
    const importReady = page.waitForResponse(r => r.url().endsWith('/api/transactions/import'))
    await page.getByRole('button', { name: /^Import \d+ transactions$/ }).click()
    const importedResponse = await importReady
    const firstImport = await importedResponse.json()
    await expect(page.getByText(/Imported 2 transaction/)).toBeVisible()
    expect(parsedPreview.import_id).toBeTruthy()
    const retry = await page.request.post('/api/transactions/import', { data: importedResponse.request().postDataJSON() })
    expect(retry.ok()).toBeTruthy()
    expect(await retry.json()).toEqual(firstImport)
    await page.reload()
    await expect(page.locator('.txn-table tbody tr')).toHaveCount(2)
    const after = await (await page.request.get(`/api/transactions?session_id=${id}`)).json()
    expect(after).toHaveLength(2) // Expense listing excludes the imported salary.
    await page.getByRole('button', { name: 'Clear all my transactions', exact: true }).click()
    await expect(page.getByText(/No transactions yet/)).toBeVisible()
    await page.getByRole('button', { name: 'Load sample transactions (demo)', exact: true }).click()
    await expect(page.locator('.txn-table tbody tr')).toHaveCount(15)
  })

  test(`${version}: all navigation destinations render without browser errors`, async ({ page }, testInfo) => {
    const errors: string[] = []
    page.on('pageerror', error => errors.push(error.message))
    await start(page, version)
    const headings: Record<string, string> = { chat: 'ARIA chat', profile: 'Your Finance Profile', progress: 'Your Learning Progress', research: 'Research reports', intelligence: 'Company intelligence', explore: 'Explore', settings: 'Settings', disclaimers: 'Disclaimers' }
    for (const route of ['chat', 'profile', 'progress', 'research', 'intelligence', 'explore', 'settings', 'disclaimers']) {
      await page.goto(`/#/${route}`)
      await expect(page.locator('main')).toBeVisible()
      await expect(page.locator('main')).not.toBeEmpty()
      await expect(page.locator('main h1')).toHaveText(headings[route])
      await testInfo.attach(`${route}-controls`, { body: JSON.stringify(await page.locator('main').locator('button,input,select,a,textarea').evaluateAll(nodes => nodes.map(n => ({ tag: n.tagName, text: n.textContent?.trim().slice(0,100), label: n.getAttribute('aria-label'), disabled: n.hasAttribute('disabled') }))), null, 2), contentType: 'application/json' })
    }
    await page.screenshot({ path: testInfo.outputPath('settings-or-disclaimers.png'), fullPage: true })
    expect(errors).toEqual([])
  })
}
