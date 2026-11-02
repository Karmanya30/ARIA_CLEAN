import fs from 'node:fs'
import { chromium, BASE, OUT, newPage } from './common.mjs'
const res = {}
const browser = await chromium.launch()
const step = async (name, fn) => { try { await fn() } catch (e) { res[name + '_ERR'] = String(e).slice(0, 240) } }
{
  const { ctx, page, log } = await newPage(browser, { width: 1440, height: 900 })
  await page.goto(`${BASE}/#/settings`); await page.waitForTimeout(1200)
  await step('skip', async () => {
    await page.locator('.skip-link').focus(); await page.keyboard.press('Enter'); await page.waitForTimeout(200)
    res.skipFocus = await page.evaluate(() => [document.activeElement?.id, location.hash])
    res.stripStop = await page.evaluate(() => { const e = document.querySelector('.aria-strip p.aria-strip-long'); const cs = getComputedStyle(e); return { overflowX: cs.overflowX, tabindex: e.getAttribute('tabindex'), sw: e.scrollWidth, cw: e.clientWidth, firstFocusable: (() => { document.activeElement.blur(); return null })() } })
    await page.keyboard.press('Tab'); res.firstTab = await page.evaluate(() => (document.activeElement.className || document.activeElement.tagName) + ' / ' + document.activeElement.textContent.trim().slice(0, 30))
  })
  await step('night', async () => {
    await page.locator('input[name=mode][value=night]').check(); await page.waitForTimeout(300)
    res.night = await page.evaluate(() => [document.documentElement.dataset.mode, localStorage.getItem('aria_mode')])
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-settings-night-1440.png` })
    await page.reload(); await page.waitForTimeout(800); res.nightPersist = await page.evaluate(() => document.documentElement.dataset.mode)
    res.settingsText = (await page.locator('main').innerText()).slice(0, 400)
    await page.locator('input[name=mode][value=light]').check()
  })
  // feedback states (mocked, never reaches mail)
  await page.goto(`${BASE}/#/feedback`); await page.waitForTimeout(800)
  await step('feedback', async () => {
    res.feedbackStatus = await page.evaluate(() => fetch('/api/feedback/status').then((r) => r.json()))
    await page.route('**/api/feedback', (r) => r.request().method() === 'POST' ? r.fulfill({ status: 500, contentType: 'application/json', body: '{"detail":"SMTP down"}' }) : r.continue())
    await page.getByLabel('Your name').fill('Test User'); await page.getByLabel('Email address').fill('t@example.test'); await page.getByLabel('How did you hear about ARIA?').selectOption('Search engine'); await page.getByLabel('Your message').fill('Synthetic message for audit only.')
    await page.getByRole('button', { name: /Send feedback/ }).click(); await page.waitForTimeout(800)
    res.feedbackError = await page.locator('.fb-error').innerText().catch(() => null)
    res.feedbackKept = await page.getByLabel('Your message').inputValue()
    await page.unroute('**/api/feedback')
    await page.route('**/api/feedback', (r) => r.request().method() === 'POST' ? r.fulfill({ status: 200, contentType: 'application/json', body: '{"sent":true}' }) : r.continue())
    await page.getByRole('button', { name: /Send feedback/ }).click(); await page.waitForTimeout(800)
    res.feedbackSuccess = await page.locator('.fb-success').innerText().catch(() => null)
    await page.unroute('**/api/feedback')
    // native validation: short message
    await page.getByRole('button', { name: 'Send another response' }).click()
    await page.getByLabel('Your message').fill('short')
    res.feedbackShortValidity = await page.getByLabel('Your message').evaluate((e) => e.validationMessage)
    res.feedbackFormErrorsAriaInvalid = await page.locator('[aria-invalid]').count()
  })
  await page.goto(`${BASE}/#/intelligence`); await page.waitForTimeout(800)
  await step('intel', async () => {
    res.intelBtn = await page.getByRole('button', { name: 'Analyse' }).evaluate((b) => [b.disabled, getComputedStyle(b).opacity])
    await page.getByRole('button', { name: 'TCS' }).click(); await page.waitForTimeout(3500)
    res.intelResult = (await page.locator('main').innerText()).slice(0, 700)
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-intel-result-1440.png` })
  })
  await page.goto(`${BASE}/#/profile`); await page.waitForTimeout(1200)
  await step('profile', async () => {
    await page.getByLabel('Age').fill('-5'); res.ageValidity = await page.getByLabel('Age').evaluate((e) => [e.min, e.max, e.validationMessage])
    await page.getByRole('button', { name: 'Save & next' }).click(); await page.waitForTimeout(500)
    res.profileAfterBadAge = (await page.locator('main').innerText()).slice(0, 300)
    // transactions
    const add = page.getByRole('button', { name: 'Add transaction' })
    res.txnForm = await page.locator('main form, main [class*=txn], main [class*=transaction]').first().innerText().catch(() => 'none')
    await add.click(); await page.waitForTimeout(500)
    res.txnEmptyAdd = await page.evaluate(() => document.querySelector('[role=alert]')?.textContent || document.activeElement?.validationMessage || 'no message')
    await page.getByRole('button', { name: /Load sample transactions/ }).click(); await page.waitForTimeout(2500)
    res.afterSample = (await page.locator('main').innerText()).slice(0, 1500)
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-profile-sample-1440.png`, fullPage: true })
    let confirmed = null; page.once('dialog', (d) => { confirmed = d.message(); d.dismiss() })
    await page.getByRole('button', { name: 'Delete all my finance data' }).click(); await page.waitForTimeout(500)
    res.deleteConfirm = confirmed
  })
  // SIP panel in explore drawer
  await page.goto(`${BASE}/#/explore`); await page.waitForTimeout(800)
  await step('sip', async () => {
    await page.getByRole('combobox').first().fill('nifty'); await page.waitForTimeout(1500); await page.getByRole('option').first().click(); await page.waitForTimeout(1500)
    const d = page.getByRole('dialog')
    res.drawerFocus = await page.evaluate(() => document.activeElement?.getAttribute('aria-label') || document.activeElement?.tagName)
    const inputs = d.locator('input[type=number], input[inputmode]')
    res.sipInputs = await inputs.count()
    if (res.sipInputs) { await inputs.first().fill('0'); await d.getByRole('button', { name: /run/i }).click().catch(() => {}); await page.waitForTimeout(800); res.sipZero = (await d.innerText()).slice(-500) }
    res.drawerKeyFacts = (await d.innerText()).match(/(Return|Cagr)[^\n]*/g)
    // focus trap
    for (let i = 0; i < 40; i++) await page.keyboard.press('Tab')
    res.drawerFocusTrap = await page.evaluate(() => !!document.activeElement.closest('[role=dialog]'))
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-drawer-sip-1440.png` })
  })
  res.console = log.console.slice(0, 8); res.http = log.http.slice(0, 8)
  await ctx.close()
}
await browser.close()
fs.writeFileSync(`${OUT}/evaluation/frontend_misc.json`, JSON.stringify(res, null, 1))
console.log(JSON.stringify(res, null, 1))
