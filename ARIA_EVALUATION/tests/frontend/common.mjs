// Shared helpers. Uses the web/ Playwright install. Offline: any non-local request is aborted and recorded.
import { createRequire } from 'node:module'
const require = createRequire('E:/ARIA/web/package.json')
export const { chromium } = require('playwright')
export const BASE = process.env.FE_BASE || 'http://127.0.0.1:5177'
export const OUT = 'E:/ARIA/ARIA_EVALUATION'
export async function newPage(browser, { width = 1440, height = 900, mode = 'light', reduced = false } = {}) {
  const ctx = await browser.newContext({ viewport: { width, height }, reducedMotion: reduced ? 'reduce' : 'no-preference', colorScheme: mode === 'night' ? 'dark' : 'light' })
  await ctx.addInitScript(([m]) => {
    for (const n of ['SpeechRecognition', 'webkitSpeechRecognition']) Object.defineProperty(window, n, { value: undefined, configurable: true })
    if (!localStorage.getItem('aria_owner_id')) localStorage.setItem('aria_owner_id', 'fe-audit-' + Math.random().toString(36).slice(2, 8))
    if (!localStorage.getItem('aria_mode')) localStorage.setItem('aria_mode', m)
    // never request the microphone
    if (navigator.mediaDevices) navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException('blocked by audit', 'NotAllowedError'))
  }, [mode])
  const page = await ctx.newPage()
  const log = { console: [], failed: [], external: [], http: [] }
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) log.console.push(`${m.type()}: ${m.text().slice(0, 200)}`) })
  page.on('pageerror', (e) => log.console.push('pageerror: ' + String(e).slice(0, 200)))
  page.on('requestfailed', (r) => log.failed.push(`${r.method()} ${r.url().slice(0, 120)} ${r.failure()?.errorText}`))
  page.on('response', (r) => { if (r.status() >= 400) log.http.push(`${r.status()} ${r.request().method()} ${r.url().slice(0, 120)}`) })
  await ctx.route(/^(?!http:\/\/127\.0\.0\.1)/, (route) => { const u = route.request().url(); if (!u.startsWith('data:') && !u.startsWith('blob:')) log.external.push(u.slice(0, 120)); return route.abort() })
  return { ctx, page, log }
}
export const ROUTES = ['markets', 'explore', 'chat', 'research', 'intelligence', 'profile', 'progress', 'feedback', 'settings', 'disclaimers']
