import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { MessageSquare, Mic, PanelLeft, Video, X } from 'lucide-react'
import { ConversationList } from './ConversationList'
import type { ChatMode } from '../types'
import { useDragWidth } from './useDragWidth'
import './HistoryPanel.css'

export const TOGGLE_HISTORY = 'aria:toggle-history'
export type Continue = { mode: ChatMode; n: number }
const WAYS: Array<{ mode: ChatMode; label: string; hint: string; icon: React.ReactNode }> = [
  { mode: 'Normal Mode', label: 'Chat', hint: 'Type and read', icon: <MessageSquare size={18} /> },
  { mode: 'Conversational Mode', label: 'Voice', hint: 'Talk, ARIA speaks back', icon: <Mic size={18} /> },
  { mode: 'Live Avatar (Free)', label: 'Video call', hint: 'Live meeting with the avatar', icon: <Video size={18} /> },
]

/** The "Chats" button for the top area. It only asks the panel to open or close. */
export function HistoryButton() {
  return (
    <button type="button" className="history-button" onClick={() => window.dispatchEvent(new Event(TOGGLE_HISTORY))}>
      <PanelLeft size={15} aria-hidden="true" /> Chats
    </button>
  )
}

/** Previous chats in a left panel that pushes the page (and the live avatar) aside, like ChatGPT's sidebar. Opening a chat asks
 * how to continue it: chat, voice or video call. */
export function HistoryPanel({ activeId, onContinue, onActiveGone }: { activeId: string; onContinue: (id: string, mode: ChatMode) => void; onActiveGone: () => void }) {
  const [open, setOpen] = useState(false)
  const size = useDragWidth('aria_history_width', 300, 220, () => Math.min(560, window.innerWidth * 0.6), (x) => x)
  const [picked, setPicked] = useState<string | null>(null)

  useEffect(() => {
    const toggle = () => setOpen((o) => !o)
    window.addEventListener(TOGGLE_HISTORY, toggle)
    return () => window.removeEventListener(TOGGLE_HISTORY, toggle)
  }, [])
  useEffect(() => {
    document.body.classList.toggle('history-open', open)
    return () => document.body.classList.remove('history-open')
  }, [open])
  useEffect(() => {
    document.documentElement.style.setProperty('--history-w', size.width + 'px')
    document.body.classList.toggle('history-resizing', size.dragging)
  }, [size.width, size.dragging])
  const dialogRef = useRef<HTMLDivElement>(null)
  useEffect(() => {  // the dialog takes focus when it opens and gives it back when it closes
    if (!picked) return
    const back = document.activeElement as HTMLElement | null
    dialogRef.current?.querySelector('button')?.focus()
    return () => back?.focus?.()
  }, [picked])
  const trapTab = (e: React.KeyboardEvent) => {
    if (e.key !== 'Tab') return
    const items = Array.from(dialogRef.current?.querySelectorAll<HTMLElement>('button') ?? [])
    const first = items[0], last = items[items.length - 1]
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus() }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus() }
  }
  useEffect(() => {
    const onKey =(e: KeyboardEvent) => { if (e.key === 'Escape') { if (picked) setPicked(null); else setOpen(false) } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [picked])

  // Rendered straight into <body> so the modal live meeting (which makes the rest of the page inert) can leave it active
  return createPortal(
    <>
      {open && <div data-keep-active className="history-backdrop" onClick={() => setOpen(false)} />}
      <aside data-keep-active id="history-panel" className={open ? 'history-panel open' : 'history-panel'} aria-label="Previous chats" aria-hidden={!open} inert={!open}>
        <div className="history-panel-head">
          <strong>Chats</strong>
          <button type="button" aria-label="Close chat history" onClick={() => setOpen(false)}><X size={16} /></button>
        </div>
        <ConversationList activeId={activeId} onSelect={setPicked} onActiveGone={onActiveGone} />
        <div className="history-resize" aria-label="Resize chat history" {...size.handle} />
      </aside>
      {picked && (
        <div data-keep-active className="continue-backdrop" onClick={() => setPicked(null)}>
          <div ref={dialogRef} className="continue-dialog" role="dialog" aria-modal="true" aria-label="How do you want to continue?" onClick={(e) => e.stopPropagation()} onKeyDown={trapTab}>
            <h2>How do you want to continue?</h2>
            <div className="continue-ways">
              {WAYS.map((w) => (
                <button key={w.label} type="button" onClick={() => { onContinue(picked, w.mode); setPicked(null); if (window.innerWidth < 900) setOpen(false) }}>
                  {w.icon}<strong>{w.label}</strong><small>{w.hint}</small>
                </button>
              ))}
            </div>
            <button type="button" className="continue-cancel" onClick={() => setPicked(null)}>Cancel</button>
          </div>
        </div>
      )}
    </>,
    document.body,
  )
}
