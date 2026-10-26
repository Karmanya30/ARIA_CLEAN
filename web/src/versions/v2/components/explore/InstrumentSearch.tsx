import { useEffect, useId, useRef, useState } from 'react'
import { Search } from 'lucide-react'
import { useInstrumentSuggestions } from '../../../../hooks/useInstrumentSuggestions'
import type { InstrumentSummary } from '../../types'
import { TYPE_CHIPS, typeLabel } from './instruments'
import './explore.css'

const TRY = ['Reliance', 'Nifty 50', 'Parag Parikh', 'Bitcoin', 'Gold', 'USD INR']

export function TypeChips({ value, onChange, label = 'Filter by type', all = true }: { value: string; onChange: (t: string) => void; label?: string; all?: boolean }) {
  return (
    <div className="ix-chips" role="group" aria-label={label}>
      {TYPE_CHIPS.filter((c) => all || c.id).map((c) => (
        <button key={c.id || 'all'} type="button" className="ix-chip" aria-pressed={value === c.id} onClick={() => onChange(c.id)}>
          {c.label}
        </button>
      ))}
    </div>
  )
}

export function ResultRow({ item, active, onPick, id }: { item: InstrumentSummary; active?: boolean; onPick: () => void; id?: string }) {
  return (
    <li id={id} role="option" aria-selected={!!active} className="ix-opt" data-active={active || undefined} onMouseDown={(e) => (e.preventDefault(), onPick())}>
      <span className="ix-opt-main">
        <b>{item.name}</b>
        <span className="ix-opt-sub">{[item.symbol, item.exchange, item.subtitle].filter(Boolean).join(' · ')}</span>
      </span>
      <span className="ix-tag">{typeLabel(item.type)}</span>
    </li>
  )
}

/** Search-as-you-type combobox over every instrument type, with type filter chips. Results are shown inline under the box. */
export function InstrumentSearch({
  onPick,
  autoFocus,
  initialType = '',
  placeholder = 'Search stocks, funds, ETFs, crypto, bonds, indices…',
  footer,
}: {
  onPick: (item: InstrumentSummary) => void
  autoFocus?: boolean
  initialType?: string
  placeholder?: string
  footer?: React.ReactNode
}) {
  const [text, setText] = useState('')
  const [type, setType] = useState(initialType)
  const [hi, setHi] = useState(0)
  const id = useId()
  const inp = useRef<HTMLInputElement>(null)
  useEffect(() => {
    if (autoFocus) inp.current?.focus()
  }, [autoFocus])
  const res = useInstrumentSuggestions(text, type)
  const term = res.query
  const items = res.items
  const note = res.data?.meta?.note
  const settling = res.settling // still typing: the request has not gone out yet
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setHi((h) => Math.max(0, Math.min(h + 1, items.length - 1)))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setHi((h) => Math.max(h - 1, 0))
    } else if (e.key === 'Enter' && items[hi]) {
      e.preventDefault()
      onPick(items[hi])
    }
  }
  return (
    <div className="ix-search">
      <div className="ix-field">
        <Search size={18} aria-hidden="true" />
        <label htmlFor={`${id}-in`} className="sr-only">
          Search all instruments
        </label>
        <input
          ref={inp}
          id={`${id}-in`}
          type="search"
          role="combobox"
          aria-expanded={items.length > 0}
          aria-controls={`${id}-lb`}
          aria-autocomplete="list"
          aria-activedescendant={items[hi] ? `${id}-o${hi}` : undefined}
          autoComplete="off"
          spellCheck={false}
          maxLength={80}
          placeholder={placeholder}
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setHi(0)
          }}
          onKeyDown={onKey}
        />
      </div>
      <TypeChips
        value={type}
        onChange={(t) => {
          setType(t)
          setHi(0)
        }}
      />
      <div aria-live="polite" className="ix-results">
        {term.length < 2 ? (
          <div className="ix-hint">
            <p>Type at least two letters. Try:</p>
            <div className="ix-chips">
              {TRY.map((t) => (
                <button
                  key={t}
                  type="button"
                  className="ix-chip ix-chip-soft"
                  onClick={() => {
                    setText(t)
                    inp.current?.focus()
                  }}
                >
                  {t}
                </button>
              ))}
            </div>
          </div>
        ) : res.error && !res.data ? (
          <p className="ix-empty" role="status">
            Search is unavailable right now. Please try again in a moment.
          </p>
        ) : !res.data || settling ? (
          <div className="ix-skels" role="status" aria-label="Searching">
            {[0, 1, 2].map((i) => (
              <span key={i} className="mk-skel" style={{ ['--h' as string]: '48px' }} />
            ))}
          </div>
        ) : items.length ? (
          <ul id={`${id}-lb`} role="listbox" aria-label="Search results" className="ix-list">
            {items.map((it, i) => (
              <ResultRow key={it.id} id={`${id}-o${i}`} item={it} active={i === hi} onPick={() => onPick(it)} />
            ))}
          </ul>
        ) : (
          <p className="ix-empty" role="status">
            {note || `No match for “${term}”${type ? ` in ${typeLabel(type).toLowerCase()}` : ''}. Check the spelling, try the ticker or the fund house name, or choose All.`}
          </p>
        )}
        {items.length > 0 && note && <p className="ix-note">{note}</p>}
      </div>
      {footer}
    </div>
  )
}
