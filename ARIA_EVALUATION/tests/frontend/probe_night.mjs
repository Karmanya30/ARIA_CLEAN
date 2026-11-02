import { chromium, BASE, newPage } from './common.mjs'
const b = await chromium.launch(); const { ctx, page } = await newPage(b, {})
await page.goto(`${BASE}/#/settings`); await page.waitForTimeout(1000)
await page.locator('input[name=mode][value=night]').check(); await page.reload(); await page.waitForTimeout(700)
console.log(await page.evaluate(() => [document.documentElement.dataset.mode, localStorage.getItem('aria_mode')]))
await b.close()
