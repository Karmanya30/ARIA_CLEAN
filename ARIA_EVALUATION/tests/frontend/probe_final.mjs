import fs from 'node:fs'
import { chromium, BASE, OUT, newPage } from './common.mjs'
const res = {}
const browser = await chromium.launch()
{
  const { ctx, page } = await newPage(browser, { width: 1440, height: 900 })
  await page.goto(`${BASE}/#/settings`); await page.waitForTimeout(1200)
  await page.locator('input[name=mode][value=night]').check(); await page.waitForTimeout(300)
  res.night = await page.evaluate(() => [document.documentElement.dataset.mode, localStorage.getItem('aria_mode')])
  await page.screenshot({ path: `${OUT}/tests/frontend/shots/e-settings-night-1440.png` })
  await page.reload(); await page.waitForTimeout(800); res.nightPersist = await page.evaluate(() => document.documentElement.dataset.mode)
  res.settingsText = (await page.locator('main').innerText()).slice(0, 400)
  // skip link on a non-default page
  await page.locator('.skip-link').focus(); await page.keyboard.press('Enter'); await page.waitForTimeout(400)
  res.skipOnSettings = { hash: await page.evaluate(() => location.hash), h1: await page.locator('main h1').allInnerTexts() }
  await ctx.close()
}
res.widths = []
for (const width of [600, 560, 520, 480, 430, 414]) {
  const { ctx, page } = await newPage(browser, { width, height: 800 })
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await page.waitForTimeout(500)
  res.widths.push([width, await page.evaluate(() => { const r = (s) => Math.round(document.querySelector(s).getBoundingClientRect().right); return { chats: r('.meeting-chats'), exit: r('.meeting-exit'), scrollW: document.querySelector('.live-meeting').scrollWidth } })])
  await ctx.close()
}
await browser.close()
fs.writeFileSync(`${OUT}/evaluation/frontend_final.json`, JSON.stringify(res, null, 1))
console.log(JSON.stringify(res))
