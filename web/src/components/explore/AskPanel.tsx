import { useEffect, useId, useRef, useState } from 'react'
import { Send } from 'lucide-react'
import { api } from '../../api'
import type { ChatResponse, InstrumentQuote } from '../../types'
import { DisclaimerLine } from '../disclaimer/DisclaimerStrip'
import { ResponseCard } from '../chat/ResponseCard'
import { ThinkingStatus } from '../chat/ThinkingStatus'
import { Provenance } from '../markets/Provenance'
import { suggestionsFor } from './instruments'

interface Turn {
  q: string
  r?: ChatResponse
  error?: string
}

/** "Ask ARIA about this": a conversation that stays in the drawer and is grounded on one instrument (the API gets its id and the earlier turns). */
export function AskPanel({ quote, sessionId, onDisclaimers }: { quote: InstrumentQuote; sessionId: string; onDisclaimers: () => void }) {
  const uid = useId()
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState('')
  const [busy, setBusy] = useState(false)
  const end = useRef<HTMLDivElement>(null)
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest', behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }) }, [turns, busy])

  async function ask(q: string) {
    q = q.trim()
    if (!q || busy) return
    const history = turns.filter((t) => t.r).flatMap((t) => [{ role: 'user' as const, content: t.q }, { role: 'assistant' as const, content: String(t.r!.response ?? '') }]).slice(-12)
    setTurns((t) => [...t, { q }])
    setText('')
    setBusy(true)
    try {
      const r = await api.askInstrument(quote.id, q, `${sessionId}:${quote.id}`, history)
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, r } : x)))
    } catch (e) {
      setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, error: e instanceof Error ? e.message : 'Something went wrong.' } : x)))
    } finally {
      setBusy(false)
    }
  }
  const retry = (i: number) => {
    const q = turns[i].q
    setTurns((t) => t.filter((_, k) => k !== i))
    void ask(q)
  }

  return (
    <section className="mk-card ix-ask" aria-labelledby={`${uid}-h`}>
      <div className="sd-h">
        <h3 id={`${uid}-h`}>Ask ARIA about {quote.name}</h3>
        <Provenance kind="ai" />
      </div>
      <DisclaimerLine onOpen={onDisclaimers} />
      {!turns.length && (
        <div className="ix-chips" role="group" aria-label="Suggested questions">
          {suggestionsFor(quote).map((s) => (
            <button key={s} type="button" className="ix-chip ix-chip-soft" onClick={() => void ask(s)}>
              {s}
            </button>
          ))}
        </div>
      )}
      <div className="ix-thread" role="log" aria-live="polite" aria-label="Conversation about this instrument">
        {turns.map((t, i) => {
          const r = t.r
          const calc = !!r && (!!r.engine || typeof r.data_basis === 'string')
          return (
            <div key={i} className="ix-turn">
              <p className="ix-q">{t.q}</p>
              {r ? (
                <div className="ix-a">
                  <ResponseCard text={r.response} />
                  <div className="ix-tags">
                    <Provenance kind="ai" />
                    {calc && <Provenance kind="calc" />}
                    {quote.source && <Provenance kind="data" source={quote.source} />}
                  </div>
                  {typeof r.data_basis === 'string' && <p className="note">{r.data_basis}</p>}
                  <p className="note">Not investment advice. Check important facts against the fund factsheet, company filings or the exchange.</p>
                </div>
              ) : t.error ? (
                <p className="ix-err" role="alert">
                  {t.error} <button type="button" className="ix-link" onClick={() => retry(i)}>Try again</button>
                </p>
              ) : null}
            </div>
          )
        })}
        {busy && <ThinkingStatus />}
        <div ref={end} />
      </div>
      <form
        className="ix-askform"
        onSubmit={(e) => {
          e.preventDefault()
          void ask(text)
        }}
      >
        <label htmlFor={`${uid}-q`} className="sr-only">Your question about {quote.name}</label>
        <input id={`${uid}-q`} className="ix-in" value={text} onChange={(e) => setText(e.target.value)} placeholder={`Ask anything about ${quote.name}…`} maxLength={500} autoComplete="off" />
        <button type="submit" className="btn primary ix-send" disabled={busy || !text.trim()} aria-label="Send question">
          <Send size={16} aria-hidden="true" />
          <span>Ask</span>
        </button>
      </form>
    </section>
  )
}
