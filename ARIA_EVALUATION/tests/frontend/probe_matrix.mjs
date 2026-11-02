import fs from 'node:fs'
import { chromium, BASE, OUT, newPage, ROUTES } from './common.mjs'
const WIDTHS = [1920, 1440, 1280, 1100, 768, 390]
const results = []
const browser = await chromium.launch()
for (const width of WIDTHS) {
  const { ctx, page, log } = await newPage(browser, { width, height: width < 800 ? 800 : 900 })
  for (const r of ROUTES) {
    log.console.length = log.failed.length = log.http.length = 0
    await page.goto(`${BASE}/#/${r}`); await page.waitForTimeout(1500)
    // leave the full-screen meeting so the page underneath can be measured
    const inMeeting = await page.locator('.live-meeting').count()
    const m = await page.evaluate(() => {
      const de = document.documentElement, vw = window.innerWidth
      const vis = (e) => { const b = e.getBoundingClientRect(); const cs = getComputedStyle(e); return b.width > 0 && b.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' }
      const name = (e) => (e.getAttribute('aria-label') || e.getAttribute('aria-labelledby') || e.textContent || e.getAttribute('title') || '').trim()
      const btns = [...document.querySelectorAll('button,[role=button],a[href]')].filter(vis)
      const unnamedBtn = btns.filter((b) => !name(b) && !b.querySelector('img[alt]')).map((b) => b.outerHTML.slice(0, 100))
      const fields = [...document.querySelectorAll('input:not([type=hidden]),select,textarea')].filter(vis)
      const unlabeled = fields.filter((f) => !(f.getAttribute('aria-label') || f.getAttribute('aria-labelledby') || (f.id && document.querySelector(`label[for="${CSS.escape(f.id)}"]`)) || f.closest('label') || f.title)).map((f) => f.outerHTML.slice(0, 100))
      const small = btns.filter((b) => { const r = b.getBoundingClientRect(); return r.width < 24 || r.height < 24 }).length
      const over = [...document.querySelectorAll('body *')].filter((e) => vis(e) && e.getBoundingClientRect().right > vw + 1 && !e.closest('.live-meeting,iframe,[aria-hidden=true],[inert],.history-panel')).slice(0, 5).map((e) => e.tagName + '.' + String(e.className).slice(0, 40))
      const tabs = [...document.querySelectorAll('[role=tab]')].map((t) => { const b = t.getBoundingClientRect(); return { n: t.textContent.trim(), r: Math.round(b.right), l: Math.round(b.left) } })
      const nav = document.querySelector('[role=tablist]')
      return { sideScroll: de.scrollWidth > vw + 1, scrollW: de.scrollWidth, h1: document.querySelectorAll('h1').length, h1text: [...document.querySelectorAll('h1')].map((h) => h.textContent.trim().slice(0, 40)), landmarks: { main: document.querySelectorAll('main').length, nav: document.querySelectorAll('nav').length }, unnamedBtn: unnamedBtn.slice(0, 5), unnamedBtnCount: unnamedBtn.length, unlabeled: unlabeled.slice(0, 5), unlabeledCount: unlabeled.length, small, over, tabs: tabs.length, tabsOut: tabs.filter((t) => t.r > vw || t.l < 0).map((t) => t.n), navOverflow: nav ? nav.scrollWidth > nav.clientWidth + 1 : null, imgNoAlt: document.querySelectorAll('img:not([alt])').length, title: document.title, lang: de.lang, mainMulti: document.querySelectorAll('main').length }
    })
    results.push({ width, route: r, inMeeting: !!inMeeting, ...m, console: [...log.console], failed: [...log.failed], http: [...log.http] })
    if ([1440, 390, 768].includes(width) && ['markets', 'chat', 'profile', 'settings'].includes(r) || (width === 1100 && r === 'chat')) await page.screenshot({ path: `${OUT}/tests/frontend/shots/m-${width}-${r}.png` })
  }
  const ext = [...new Set(log.external)]
  results.push({ width, externalRequests: ext })
  await ctx.close()
}
await browser.close()
fs.writeFileSync(`${OUT}/evaluation/frontend_matrix.json`, JSON.stringify(results, null, 1))
for (const x of results) { if (x.route) console.log(x.width, x.route, x.inMeeting ? 'MTG' : '', 'side=' + x.sideScroll, 'h1=' + x.h1, 'unnB=' + x.unnamedBtnCount, 'unlab=' + x.unlabeledCount, 'small=' + x.small, 'tabsOut=' + x.tabsOut.join('|'), 'navOv=' + x.navOverflow, 'over=' + x.over.length, 'con=' + x.console.length, 'fail=' + x.failed.length, 'http=' + x.http.length); else console.log(x.width, 'external', x.externalRequests) }
