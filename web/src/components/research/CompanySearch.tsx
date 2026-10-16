import { useId, useState } from 'react'
import { useInstrumentSuggestions } from '../../hooks/useInstrumentSuggestions'
import type { InstrumentSummary } from '../../types'
import './CompanySearch.css'

export function CompanySearch({ value, onChange, onPick, label = 'Company', disabled = false }: {
  value: string; onChange: (text: string) => void; onPick: (item: InstrumentSummary) => void
  label?: string; disabled?: boolean
}) {
  const id = useId()
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const res = useInstrumentSuggestions(value, 'stock', 'india')
  const items = open && !disabled ? res.items : []
  const pick = (item: InstrumentSummary) => { setOpen(false); onPick(item) }
  return <div className="company-search">
    <input aria-label={label} role="combobox" aria-autocomplete="list" autoComplete="off"
      aria-expanded={items.length > 0} aria-controls={items.length ? `${id}-list` : undefined}
      aria-activedescendant={items[active] ? `${id}-${active}` : undefined}
      placeholder="Start typing a company name or ticker…" value={value} disabled={disabled} maxLength={80}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)}
      onChange={e => { onChange(e.target.value); setOpen(true); setActive(0) }}
      onKeyDown={e => {
        if (e.key === 'Escape') { setOpen(false); e.preventDefault() }
        else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
          e.preventDefault(); setOpen(true)
          setActive(n => !open ? 0 : Math.max(0, Math.min(res.items.length - 1, n + (e.key === 'ArrowDown' ? 1 : -1))))
        } else if (e.key === 'Enter' && items[active]) { e.preventDefault(); pick(items[active]) }
      }} />
    {items.length > 0 && <ul id={`${id}-list`} role="listbox" aria-label={`${label} suggestions`}>
      {items.map((item, i) => <li key={item.id} id={`${id}-${i}`} role="option" aria-selected={i === active}
        onMouseDown={e => e.preventDefault()} onClick={() => pick(item)}>
        <b>{item.name}</b><span>{item.symbol} · {item.exchange}</span>
      </li>)}
    </ul>}
    {open && res.query.length >= 2 && <p className="company-search-status" role="status">
      {res.settling || res.loading ? 'Searching companies…' : res.error ? 'Company suggestions unavailable. Try again or enter a ticker.'
        : res.items.length ? 'Choose a company, or use ↑ ↓ and Enter.' : 'No matching listed company. Try a shorter name or ticker.'}
    </p>}
  </div>
}
