import fs from 'node:fs'
import { chromium, BASE, OUT, newPage, ROUTES } from './common.mjs'
const res = { contrast: {}, tabs: {}, motion: {}, small: {}, misc: {} }
const browser = await chromium.launch()
const leave = async (page) => { await page.waitForTimeout(400); if (await page.locator('.live-meeting').count()) { await page.getByRole('button', { name: 'End session' }).click(); await page.waitForTimeout(500) } }
const CONTRAST = () => {
  const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 } }
  const lum = ({ r, g, b }) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4 }; return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b) }
  const over = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 })
  const bgOf = (el) => { let stack = []; for (let e = el; e; e = e.parentElement) { const cs = getComputedStyle(e); if (cs.backgroundImage !== 'none') return null; const c = parse(cs.backgroundColor); if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break } } let base = { r: 255, g: 255, b: 255, a: 1 }; for (const c of stack.reverse()) base = over(c, base); return base }
  const out = {}; let checked = 0, bad = 0
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const seen = new Set()
  while (walker.nextNode()) {
    const n = walker.currentNode; if (!n.textContent.trim()) continue
    const el = n.parentElement; if (!el || seen.has(el) || el.closest('script,style,svg,[inert],[aria-hidden=true]')) continue
    seen.add(el)
    const cs = getComputedStyle(el); const b = el.getBoundingClientRect()
    if (b.width < 2 || b.height < 2 || cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue
    const bg = bgOf(el); if (!bg) continue
    let fg = parse(cs.color); if (!fg) continue; fg = over({ ...fg, a: fg.a * (+cs.opacity) }, bg)
    const ratio = (Math.max(lum(fg), lum(bg)) + 0.05) / (Math.min(lum(fg), lum(bg)) + 0.05)
    const size = parseFloat(cs.fontSize), bold = +cs.fontWeight >= 700
    const need = size >= 24 || (size >= 18.66 && bold) ? 3 : 4.5
    checked++
    if (ratio < need) { bad++; const key = el.tagName.toLowerCase() + '.' + String(el.className).split(' ')[0]; (out[key] ||= { n: 0, ratio: +ratio.toFixed(2), need, size, sample: n.textContent.trim().slice(0, 30), fg: cs.color, bg: `rgb(${Math.round(bg.r)},${Math.round(bg.g)},${Math.round(bg.b)})` }).n++ }
  }
  return { checked, bad, top: Object.entries(out).sort((a, b) => b[1].n - a[1].n).slice(0, 8) }
}
const routes = ROUTES.filter((r) => r !== 'chat')
for (const mode of ['light', 'night']) {
  const { ctx, page } = await newPage(browser, { width: 1440, height: 900, mode })
  for (const r of routes) {
    await page.goto(`${BASE}/#/${r}`); await page.waitForTimeout(1300)
    res.contrast[`${mode}:${r}`] = await page.evaluate(CONTRAST)
  }
  await page.goto(`${BASE}/#/chat`); await leave(page); await page.waitForTimeout(500)
  res.contrast[`${mode}:chat-normal`] = await page.evaluate(CONTRAST)
  await ctx.close()
}
// keyboard
{
  const { ctx, page } = await newPage(browser, { width: 1440, height: 900 })
  for (const r of routes) {
    await page.goto(`${BASE}/#/${r}`); await page.waitForTimeout(1000)
    await page.evaluate(() => document.activeElement?.blur()); await page.keyboard.press('Tab')
    const stops = []
    for (let i = 0; i < 22; i++) {
      stops.push(await page.evaluate(() => { const e = document.activeElement; const cs = getComputedStyle(e); const ring = (cs.outlineStyle !== 'none' && parseFloat(cs.outlineWidth) > 0) || cs.boxShadow !== 'none'; const b = e.getBoundingClientRect(); return `${(e.getAttribute('aria-label') || e.textContent || e.tagName).trim().replace(/\s+/g, ' ').slice(0, 26)}|${ring ? 'ring' : 'NORING'}|${b.width > 0 && b.bottom > 0 && b.top < innerHeight ? 'vis' : 'OFF'}` }))
      await page.keyboard.press('Tab')
    }
    res.tabs[r] = { first: stops.slice(0, 14), noRing: stops.filter((s) => s.includes('NORING')).length, off: stops.filter((s) => s.includes('|OFF')).length }
  }
  // skip link
  await page.goto(`${BASE}/#/settings`); await page.waitForTimeout(600); await page.evaluate(() => document.activeElement?.blur()); await page.keyboard.press('Tab')
  res.misc.firstTabStop = await page.evaluate(() => document.activeElement.textContent.trim().slice(0, 40))
  await page.keyboard.press('Enter'); res.misc.skipLinkMovesFocus = await page.evaluate(() => document.activeElement?.id)
  // tab roles: tablist keyboard
  res.misc.navRole = await page.evaluate(() => { const n = document.querySelector('[role=tablist]'); const t = n.querySelector('[role=tab]'); return { tablistParent: n.parentElement.tagName, tabindexes: [...n.querySelectorAll('[role=tab]')].map((x) => x.tabIndex).join(','), hasTabpanel: document.querySelectorAll('[role=tabpanel]').length, ariaControls: t.getAttribute('aria-controls') } })
  await page.goto(`${BASE}/#/settings`); await page.waitForTimeout(500)
  await page.locator('[role=tab][aria-selected=true]').focus(); await page.keyboard.press('ArrowRight')
  res.misc.arrowMovesTab = await page.evaluate(() => document.activeElement.textContent.trim())
  // tab title per route
  res.misc.titles = {}
  for (const r of ROUTES) { await page.goto(`${BASE}/#/${r}`); await page.waitForTimeout(300); res.misc.titles[r] = await page.title() }
  await ctx.close()
}
// reduced motion
for (const reduced of [false, true]) {
  const { ctx, page } = await newPage(browser, { width: 1440, height: 900, reduced })
  const m = {}
  for (const r of ['markets', 'explore', 'settings', 'chat']) {
    await page.goto(`${BASE}/#/${r}`); await page.waitForTimeout(1500)
    m[r] = await page.evaluate(() => document.getAnimations().filter((a) => a.playState === 'running').map((a) => (a.animationName || a.transitionProperty || a.constructor.name) + ':' + (a.effect?.getComputedTiming().iterations === Infinity ? 'inf' : 'fin')).reduce((acc, x) => (acc[x] = (acc[x] || 0) + 1, acc), {}))
  }
  res.motion[reduced ? 'reduce' : 'normal'] = m
  await ctx.close()
}
// touch targets at 390
{
  const { ctx, page } = await newPage(browser, { width: 390, height: 800 })
  for (const r of ['markets', 'explore', 'research', 'profile', 'settings', 'feedback']) {
    await page.goto(`${BASE}/#/${r}`); await page.waitForTimeout(1000)
    res.small[r] = await page.evaluate(() => [...document.querySelectorAll('button,a[href],[role=tab],input:not([type=hidden]),select,[role=switch]')].filter((e) => { const b = e.getBoundingClientRect(); const cs = getComputedStyle(e); return b.width > 0 && cs.visibility !== 'hidden' && (b.height < 44 || b.width < 44) && !e.closest('[inert]') }).reduce((acc, e) => { const k = (e.getAttribute('aria-label') || e.textContent || e.tagName).trim().slice(0, 22) + ` ${Math.round(e.getBoundingClientRect().width)}x${Math.round(e.getBoundingClientRect().height)}`; acc.push(k); return acc }, []).slice(0, 14))
  }
  await ctx.close()
}
await browser.close()
fs.writeFileSync(`${OUT}/evaluation/frontend_a11y.json`, JSON.stringify(res, null, 1))
for (const [k, v] of Object.entries(res.contrast)) console.log('C', k, v.checked, v.bad, JSON.stringify(v.top.slice(0, 3)))
console.log(JSON.stringify({ tabs: res.tabs, misc: res.misc, motion: res.motion, small: res.small }))
