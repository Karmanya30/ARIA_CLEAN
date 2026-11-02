import fs from 'node:fs'
import { chromium, BASE, OUT, newPage } from './common.mjs'
const res = {}
const browser = await chromium.launch()
const names = (page, sel) => page.locator(sel).evaluateAll((els) => els.map((e) => (e.getAttribute('aria-label') || e.textContent || '').trim().slice(0, 40)))
const step = async (name, fn) => { try { await fn() } catch (e) { res[name + '_ERR'] = String(e).slice(0, 200) } }
{
  const { ctx, page, log } = await newPage(browser, { width: 1440, height: 900 })
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await page.waitForTimeout(500)
  await step('meeting', async () => {
    await page.getByRole('button', { name: 'Toggle chat' }).click({ force: true })
    await page.waitForTimeout(800)
    res.meetingNoStart = { composerDisabled: await page.getByRole('textbox', { name: 'Message ARIA' }).isDisabled(), placeholder: await page.getByRole('textbox', { name: 'Message ARIA' }).getAttribute('placeholder'), suggestionsDisabled: await page.locator('.meeting-empty button').evaluateAll(b => b.map(x => x.disabled)) }
    const h = await page.locator('.meeting-resize').boundingBox()
    await page.mouse.move(h.x + 6, 400); await page.mouse.down(); await page.mouse.move(h.x - 120, 400, { steps: 6 }); await page.mouse.up()
    res.meetingResize = { w: (await page.locator('.meeting-chat').boundingBox()).width, stored: await page.evaluate(() => localStorage.getItem('aria_meeting_chat_width')) }
    await page.locator('.meeting-resize').focus(); await page.keyboard.press('ArrowLeft')
    res.meetingResizeKey = (await page.locator('.meeting-chat').boundingBox()).width
    await page.keyboard.press('Escape'); await page.waitForTimeout(500)
    res.escapeFromHandleClosed = await page.locator('#meeting-chat').evaluate((e) => e.inert)
    await page.getByRole('button', { name: 'Toggle chat' }).click(); await page.waitForTimeout(600)
    await page.mouse.click(300, 400); await page.keyboard.press('Escape'); await page.waitForTimeout(500)
    res.escapeAfterClickStageClosed = await page.locator('#meeting-chat').evaluate((e) => e.inert)
    await page.getByRole('button', { name: 'End session' }).click(); await page.waitForTimeout(600)
    res.leaveWithoutDraft = await page.locator('.live-meeting').count()
  })
  await step('hero', async () => {
    res.hero = { h: await page.locator('h1,h2').allInnerTexts(), buttons: await names(page, 'main button'), mode: await page.locator('#chat-mode').inputValue(), modes: await names(page, '#chat-mode option') }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/c-hero-1440.png` })
    res.sendDisabledEmpty = await page.getByRole('button', { name: 'Send message' }).isDisabled()
  })
  const box = page.getByRole('textbox', { name: 'Message ARIA' })
  await step('busy', async () => {
    await page.route('**/api/chat', async (r) => { if (r.request().method() === 'POST') await new Promise((s) => setTimeout(s, 2500)); r.continue() })
    await box.fill('what is a SIP'); await box.press('Enter'); await page.waitForTimeout(700)
    res.busy = { stop: await page.getByRole('button', { name: 'Stop' }).count(), inputDisabled: await box.isDisabled(), thinking: (await page.locator('.message-pair').last().innerText()).slice(0, 120) }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/c-busy-1440.png` })
    await page.waitForTimeout(3500)
    res.reply = { text: (await page.locator('.chat-thread').innerText()).slice(0, 400), actions: await names(page, '.chat-thread button'), roles: await page.locator('.chat-thread [role]').evaluateAll((e) => [...new Set(e.map((x) => x.getAttribute('role')))]), images: await page.locator('.chat-thread img').count() }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/c-reply-1440.png` })
  })
  for (const [k, status, body] of [['abort', 0, ''], ['err500', 500, '{"detail":"Internal error: Traceback (most recent call last) boom"}'], ['err429', 429, '{"detail":"Too many requests"}']]) {
    await step(k, async () => {
      await page.unroute('**/api/chat').catch(() => {})
      await page.route('**/api/chat', (r) => r.request().method() !== 'POST' ? r.continue() : status ? r.fulfill({ status, contentType: 'application/json', body }) : r.abort('failed'))
      await box.fill('q ' + k); await box.press('Enter'); await page.waitForTimeout(1200)
      res[k] = (await page.locator('.chat-thread').innerText()).slice(-160)
      if (k === 'err500') await page.screenshot({ path: `${OUT}/tests/frontend/shots/c-error-1440.png` })
    })
  }
  await page.unroute('**/api/chat').catch(() => {})
  await step('clear', async () => {
    let confirmed = false; page.once('dialog', (d) => { confirmed = true; d.accept() })
    await page.getByRole('button', { name: 'Clear chat' }).click(); await page.waitForTimeout(800)
    res.clear = { nativeConfirm: confirmed, hero: await page.locator('.chat-idle-block').count() }
  })
  await step('conv', async () => {
    await page.locator('#chat-mode').selectOption('Conversational Mode'); await page.waitForTimeout(1200)
    res.conversational = { h1: await page.locator('h1').allInnerTexts(), buttons: await names(page, 'main button') }
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/c-conversational-1440.png` })
  })
  res.consoleErrors = log.console.slice(0, 8)
  await ctx.close()
}
{
  const { ctx, page, log } = await newPage(browser, { width: 1440, height: 900 })
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await page.waitForTimeout(500)
  await page.getByRole('button', { name: 'End session' }).click(); await page.waitForTimeout(500)
  res.hist = {}
  await step('hist', async () => {
    for (const q of ['what is a mutual fund', 'explain SIP']) {
      const box = page.getByRole('textbox', { name: 'Message ARIA' }); await box.fill(q); await box.press('Enter'); await page.waitForTimeout(1800)
      await page.getByRole('button', { name: /New chat/ }).click(); await page.waitForTimeout(500)
      if (await page.locator('.live-meeting').count()) { await page.getByRole('button', { name: 'End session' }).click(); await page.waitForTimeout(400) }
    }
    await page.getByRole('button', { name: 'Chats' }).first().click(); await page.waitForTimeout(700)
    res.hist.panel = (await page.locator('#history-panel').innerText()).slice(0, 400)
    res.hist.buttons = await names(page, '#history-panel button')
    res.hist.layout = await page.evaluate(() => { const m = document.querySelector('.app-main').getBoundingClientRect(); const p = document.querySelector('#history-panel').getBoundingClientRect(); return { panel: [p.left, p.right], main: [Math.round(m.left), Math.round(m.right)] } })
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/h-panel-1440.png` })
    const search = page.locator('#history-panel input').first()
    await search.fill('zzzzqq'); await page.waitForTimeout(900)
    res.hist.emptySearch = (await page.locator('#history-panel').innerText()).slice(-160)
    await search.fill(''); await page.waitForTimeout(700)
    await page.locator('#history-panel li').first().locator('button').first().click(); await page.waitForTimeout(500)
    res.hist.continueDialog = await page.getByRole('dialog', { name: 'How do you want to continue?' }).count()
    res.hist.continueFocus = await page.evaluate(() => document.activeElement?.textContent?.slice(0, 30))
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/h-continue-1440.png` })
    await page.keyboard.press('Escape'); await page.waitForTimeout(300)
    res.hist.afterEsc = { dialog: await page.getByRole('dialog', { name: 'How do you want to continue?' }).count(), panelOpen: await page.locator('#history-panel.open').count() }
  })
  res.hist.console = log.console.slice(0, 5)
  await ctx.close()
}
{
  const { ctx, page } = await newPage(browser, { width: 390, height: 800 })
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await page.waitForTimeout(500)
  await page.getByRole('button', { name: 'End session' }).click(); await page.waitForTimeout(500)
  await step('h390', async () => {
    await page.getByRole('button', { name: 'Chats' }).first().click(); await page.waitForTimeout(700)
    res.hist390 = await page.evaluate(() => { const p = document.querySelector('#history-panel').getBoundingClientRect(); return [Math.round(p.left), Math.round(p.right), innerWidth, document.documentElement.scrollWidth] })
    await page.screenshot({ path: `${OUT}/tests/frontend/shots/h-panel-390.png` })
  })
  await ctx.close()
}
await browser.close()
fs.writeFileSync(`${OUT}/evaluation/frontend_chat.json`, JSON.stringify(res, null, 1))
console.log(JSON.stringify(res, null, 1))
