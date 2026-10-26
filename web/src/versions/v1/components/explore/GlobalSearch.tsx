import { useEffect, useRef, useState } from 'react'
import { Search, X } from 'lucide-react'
import { InstrumentSearch } from './InstrumentSearch'
import './explore.css'

/** Header search button (every page, every theme). Opens a palette to find any stock, fund, ETF, coin, bond, index, commodity or currency.
 * Ctrl/Cmd+K or "/" opens it from anywhere. */
export function GlobalSearch({ onOpenInstrument, onBrowse, label = 'Search' }: { onOpenInstrument: (id: string) => void; onBrowse: () => void; label?: string }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      const typing = !!t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName))
      if (((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') || (e.key === '/' && !typing && !e.ctrlKey && !e.metaKey)) {
        e.preventDefault()
        setOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
  return (
    <>
      <button type="button" className="gs-btn" onClick={() => setOpen(true)} aria-label={`${label} all instruments`} aria-haspopup="dialog" aria-keyshortcuts="Control+K">
        <Search size={16} aria-hidden="true" />
        <span className="gs-label">{label}</span>
        <kbd className="gs-kbd" aria-hidden="true">/</kbd>
      </button>
      {open && (
        <Palette
          onClose={() => setOpen(false)}
          onPick={(id) => {
            setOpen(false)
            onOpenInstrument(id)
          }}
          onBrowse={() => {
            setOpen(false)
            onBrowse()
          }}
        />
      )}
    </>
  )
}

function Palette({ onClose, onPick, onBrowse }: { onClose: () => void; onPick: (id: string) => void; onBrowse: () => void }) {
  const dlg = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const d = dlg.current!
    const opener = document.activeElement as HTMLElement | null
    d.showModal()
    return () => {
      d.close()
      opener?.focus?.()
    }
  }, [])
  return (
    <dialog ref={dlg} className="gs-dlg" aria-label="Search all instruments" onCancel={(e) => (e.preventDefault(), onClose())} onClick={(e) => e.target === dlg.current && onClose()}>
      <div className="gs-body">
        <div className="gs-head">
          <h2>Search anything tradable</h2>
          <button type="button" className="gs-x" onClick={onClose} aria-label="Close search">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <InstrumentSearch
          autoFocus
          onPick={(it) => onPick(it.id)}
          footer={
            <button type="button" className="gs-browse" onClick={onBrowse}>
              Browse all categories in Explore
            </button>
          }
        />
      </div>
    </dialog>
  )
}
