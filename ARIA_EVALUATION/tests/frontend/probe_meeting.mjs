import fs from 'node:fs'
import { chromium, BASE, OUT, newPage } from './common.mjs'
const res = {}
const STUB = `<!doctype html><title>stub</title><body style="background:#123;color:#9fc">stub avatar<script>
let st={status:'ready',label:'Ready',connected:true,started:true,micOn:false,listening:false,speaking:false,supported:true,processing:false};
const send=(m)=>parent.postMessage(Object.assign({source:'aria-live'},m),location.origin);
addEventListener('message',e=>{const d=e.data||{};if(d.source!=='aria-meeting')return;
 if(d.type==='ask'){send({type:'user',turn:1,text:d.text});setTimeout(()=>send({type:'text',turn:1,text:'Synthetic **reply** for audit.'}),150);setTimeout(()=>send({type:'done',turn:1}),300)}
 if(d.type==='mic'){st={...st,micOn:!st.micOn};send({type:'state',state:st})}
 if(d.type==='end'){send({type:'ended'})}});
setTimeout(()=>send({type:'state',state:st}),200);
</script>`
const browser = await chromium.launch()
res.header = []
for (const width of [1920, 1440, 1280, 1100, 768, 390]) {
  const { ctx, page } = await newPage(browser, { width, height: 800 })
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await page.waitForTimeout(600)
  res.header.push({ width, ...(await page.evaluate(() => { const r = (s) => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return { l: Math.round(b.left), r: Math.round(b.right), w: Math.round(b.width), h: Math.round(b.height) } }; return { vw: innerWidth, chats: r('.meeting-chats'), exit: r('.meeting-exit'), avatar: r('.meeting-avatar select'), controls: r('.meeting-controls') } })) })
  await ctx.close()
}
{
  const { ctx, page, log } = await newPage(browser, { width: 1440, height: 900 })
  await ctx.route('**/avatar/live**', (r) => r.fulfill({ contentType: 'text/html', body: STUB }))
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await page.waitForTimeout(800)
  const b = {}
  b.statusText = await page.locator('.meeting-status').innerText()
  b.connected = await page.locator('.meeting-connection').innerText()
  await page.screenshot({ path: `${OUT}/tests/frontend/shots/b-meeting-1440.png` })
  const order = []
  await page.locator('.meeting-header select').focus()
  for (let i = 0; i < 12; i++) { await page.keyboard.press('Tab'); order.push(await page.evaluate(() => { const e = document.activeElement; return (e.getAttribute('aria-label') || e.textContent || e.tagName).trim().slice(0, 28) + (e.closest('.live-meeting') ? '' : ' [OUTSIDE]') })) }
  b.tabOrder = order
  b.chatInertClosed = await page.locator('#meeting-chat').evaluate(e => e.inert)
  await page.getByRole('button', { name: 'Toggle chat' }).click(); await page.waitForTimeout(400)
  b.chatInertOpen = await page.locator('#meeting-chat').evaluate(e => e.inert)
  b.focusAfterOpen = await page.evaluate(() => document.activeElement?.getAttribute('aria-label'))
  const ta = page.getByRole('textbox', { name: 'Message ARIA' })
  await ta.fill('What is a SIP?'); await ta.press('Enter'); await page.waitForTimeout(900)
  b.transcript = (await page.locator('.meeting-messages').innerText()).slice(0, 300)
  await page.screenshot({ path: `${OUT}/tests/frontend/shots/b-meeting-chat-1440.png` })
  const h = await page.locator('.meeting-resize').boundingBox()
  const w0 = (await page.locator('.meeting-chat').boundingBox()).width
  await page.mouse.move(h.x + 3, h.y + 200); await page.mouse.down(); await page.mouse.move(h.x - 150, h.y + 200, { steps: 5 }); await page.mouse.up()
  const w1 = (await page.locator('.meeting-chat').boundingBox()).width
  b.resize = { before: w0, after: w1, stored: await page.evaluate(() => localStorage.getItem('aria_meeting_chat_width')) }
  b.resizeHandleAttrs = await page.locator('.meeting-resize').evaluate(e => ({ role: e.getAttribute('role'), tabindex: e.getAttribute('tabindex'), ariaValue: e.getAttribute('aria-valuenow') }))
  await page.keyboard.press('Escape'); await page.waitForTimeout(300)
  b.escapeClosed = await page.locator('#meeting-chat').evaluate(e => e.inert)
  let dlg = null; page.once('dialog', async d => { dlg = d.message(); await d.dismiss() })
  await page.locator('select[aria-label=Avatar]').selectOption('new'); await page.waitForTimeout(300)
  b.avatarConfirm = dlg; b.avatarAfterDismiss = await page.locator('select[aria-label=Avatar]').inputValue()
  await page.getByRole('button', { name: 'Chat history' }).click(); await page.waitForTimeout(400)
  b.historyOpenInMeeting = await page.locator('#history-panel.open').count()
  b.historyZ = await page.evaluate(() => { const p = document.querySelector('#history-panel').getBoundingClientRect(); const z = (s) => getComputedStyle(document.querySelector(s)).zIndex; return { panel: [Math.round(p.left), Math.round(p.right)], zPanel: z('#history-panel'), zMeeting: z('.live-meeting') } })
  await page.screenshot({ path: `${OUT}/tests/frontend/shots/b-meeting-history-1440.png` })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: 'Toggle chat' }).click(); await page.getByRole('textbox', { name: 'Message ARIA' }).fill('draft')
  await page.getByRole('button', { name: 'End session' }).click(); await page.waitForTimeout(300)
  b.confirmShown = await page.getByRole('alertdialog').count()
  b.confirmFocus = await page.evaluate(() => document.activeElement?.textContent)
  await page.getByRole('button', { name: 'Leave meeting' }).last().click(); await page.waitForTimeout(800)
  b.afterLeave = { meeting: await page.locator('.live-meeting').count(), mode: await page.locator('#chat-mode').inputValue().catch(() => null), h1: await page.locator('h1').allInnerTexts() }
  await page.screenshot({ path: `${OUT}/tests/frontend/shots/b-after-leave-1440.png` })
  b.console = log.console.slice(0, 6)
  res.meeting = b
  await ctx.close()
}
{
  const { ctx, page } = await newPage(browser, { width: 390, height: 800 })
  await ctx.route('**/avatar/live**', (r) => r.fulfill({ contentType: 'text/html', body: STUB }))
  await page.goto(`${BASE}/#/chat`); await page.waitForSelector('.live-meeting'); await page.waitForTimeout(800)
  await page.getByRole('button', { name: 'Toggle chat' }).click(); await page.waitForTimeout(500)
  res.meeting390 = await page.evaluate(() => { const r = (s) => { const e = document.querySelector(s); const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right), Math.round(b.top), Math.round(b.bottom)] }; return { chat: r('.meeting-chat'), composer: r('.meeting-composer'), controls: r('.meeting-controls'), vh: innerHeight } })
  await page.screenshot({ path: `${OUT}/tests/frontend/shots/b-meeting-chat-390.png` })
  await ctx.close()
}
await browser.close()
fs.writeFileSync(`${OUT}/evaluation/frontend_meeting.json`, JSON.stringify(res, null, 1))
console.log(JSON.stringify(res))
