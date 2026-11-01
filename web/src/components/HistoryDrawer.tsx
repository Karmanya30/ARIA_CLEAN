import { useEffect, useState } from 'react'
import { PanelLeft, X } from 'lucide-react'
import { ConversationList } from './ConversationList'
import './HistoryDrawer.css'

/** The chat history as a left drawer, opened from a button on the Chat page only (like ChatGPT's sidebar). */
export function HistoryDrawer({ activeId, onSelect, onActiveGone }: { activeId: string; onSelect: (id: string) => void; onActiveGone: () => void }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  return (
    <>
      <button type="button" className="history-toggle" aria-expanded={open} aria-controls="history-drawer" onClick={() => setOpen((o) => !o)}>
        <PanelLeft size={16} aria-hidden="true" /> <span>Chats</span>
      </button>
      {open && <div className="history-backdrop" onClick={() => setOpen(false)} />}
      <aside id="history-drawer" className={open ? 'history-drawer open' : 'history-drawer'} aria-label="Previous chats" aria-hidden={!open} inert={!open}>
        <div className="history-drawer-head">
          <strong>Chats</strong>
          <button type="button" aria-label="Close chat history" onClick={() => setOpen(false)}><X size={16} /></button>
        </div>
        <ConversationList activeId={activeId} onSelect={(id) => { onSelect(id); setOpen(false) }} onActiveGone={onActiveGone} />
      </aside>
    </>
  )
}
