import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Captions, MessageSquare, Mic, MicOff, PhoneOff, Send, Square, X } from 'lucide-react'
import { api, ownerId } from '../../api'
import type { HistoryTurn } from '../../types'
import { Markdown } from './Markdown'
import { BrandLogo, BrandMark } from '../brand/BrandLogo'
import './LiveMeeting.css'

type LiveState = { status: string; label: string; connected: boolean; started: boolean; micOn: boolean; listening: boolean; speaking: boolean; supported: boolean; processing: boolean }
const initialState: LiveState = { status: 'connecting', label: 'Preparing your meeting…', connected: false, started: false, micOn: false, listening: false, speaking: false, supported: true, processing: false }

/** The iframe owns the existing voice engine; this shell owns presentation only. */
export function LiveMeeting({ sessionId, history, onHistory, onEnd }: {
  sessionId: string; history: HistoryTurn[]; onHistory: (history: HistoryTurn[]) => void; onEnd: () => void
}) {
  const frame = useRef<HTMLIFrameElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const chatButton = useRef<HTMLButtonElement>(null)
  const scroll = useRef<HTMLDivElement>(null)
  const [state, setState] = useState(initialState)
  const [chatOpen, setChatOpen] = useState(false)
  const [captions, setCaptions] = useState(true)
  const [query, setQuery] = useState('')
  const [pending, setPending] = useState<{ query: string; response: string; turn: number; historyIndex: number; interrupted?: boolean } | null>(null)
  const [error, setError] = useState('')
  const [syncError, setSyncError] = useState('')
  const [elapsed, setElapsed] = useState(0)
  const [confirmEnd, setConfirmEnd] = useState(false)
  const [src] = useState(() => `/avatar/live?session_id=${encodeURIComponent(sessionId)}&owner_id=${encodeURIComponent(ownerId())}&meeting=1`)
  const activeTurn = useRef(0)
  const historyRef = useRef(history)
  const followTranscript = useRef(true)
  historyRef.current = history
  const callbacks = useRef({ onHistory, onEnd })
  callbacks.current = { onHistory, onEnd }

  function command(type: string, extra: Record<string, unknown> = {}) {
    frame.current?.contentWindow?.postMessage({ source: 'aria-meeting', type, ...extra }, location.origin)
  }

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null
    const siblings = [...document.body.children].filter(el => el !== document.querySelector('.live-meeting')) as HTMLElement[]
    const previous = siblings.map(el => el.inert)
    siblings.forEach(el => { el.inert = true })
    const overflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    let alive = true, revision = 0
    let completedTurnId: number | undefined
    async function refresh(completedTurn?: number) {
      if (completedTurn !== undefined) completedTurnId = completedTurn
      const request = ++revision
      try {
        const result = await api.getHistory(sessionId)
        if (!alive || request !== revision) return
        callbacks.current.onHistory(result.history as HistoryTurn[])
        setPending(p => p && (p.turn === completedTurnId || (p.interrupted && (result.history as HistoryTurn[]).slice(p.historyIndex).some(t => t.query === p.query))) ? null : p)
        setSyncError('')
      } catch { if (alive) setSyncError('Transcript sync is delayed. Your conversation is still available in this session.') }
    }
    const receive = (ev: MessageEvent) => {
      if (ev.origin !== location.origin || ev.source !== frame.current?.contentWindow || ev.data?.source !== 'aria-live') return
      const m = ev.data
      if (m.type === 'state') setState(m.state)
      if (m.type === 'user') { activeTurn.current = m.turn; setError(''); followTranscript.current = true; setPending({ query: m.text, response: '', turn: m.turn, historyIndex: historyRef.current.length }) }
      if (m.type === 'text' && m.turn === activeTurn.current) setPending(p => p ? { ...p, response: p.response + m.text } : p)
      if (m.type === 'done') void refresh(m.turn)
      if (m.type === 'interrupted') { void refresh(); setPending(p => p ? { ...p, interrupted: true, response: p.response || 'Response interrupted.' } : p) }
      if (m.type === 'ended') callbacks.current.onEnd()
      if (m.type === 'error') { setError(m.message); if (m.turn !== undefined) void refresh(m.turn) }
      if (m.type === 'escape') { setChatOpen(false); chatButton.current?.focus() }
    }
    window.addEventListener('message', receive)
    const poll = setInterval(() => void refresh(), 4000)
    void refresh()
    return () => {
      alive = false
      clearInterval(poll)
      command('end')
      window.removeEventListener('message', receive)
      document.body.style.overflow = overflow
      siblings.forEach((el, i) => { el.inert = previous[i] })
      requestAnimationFrame(() => {
        if (previousFocus?.isConnected) previousFocus.focus()
        else document.getElementById('chat-mode')?.focus()
      })
    }
  }, [sessionId])

  useEffect(() => {
    if (!state.started) return
    const start = Date.now()
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000)
    return () => clearInterval(timer)
  }, [state.started])

  useEffect(() => {
    if (!chatOpen) return
    const timer = requestAnimationFrame(() => input.current?.focus())
    return () => cancelAnimationFrame(timer)
  }, [chatOpen])
  useEffect(() => {
    const el = scroll.current
    if (el && followTranscript.current) el.scrollTop = el.scrollHeight
  }, [history, pending])

  function closeChat() { setChatOpen(false); chatButton.current?.focus() }
  function send(text = query) {
    if (!text.trim() || !state.connected || !state.started) return
    command('ask', { text: text.trim() }); setQuery('')
  }
  function end() {
    if (query.trim() || state.processing) { setConfirmEnd(true); return }
    command('end'); onEnd()
  }
  const clock = `${Math.floor(elapsed / 60).toString().padStart(2, '0')}:${(elapsed % 60).toString().padStart(2, '0')}`

  return createPortal(
    <section className={`live-meeting${chatOpen ? ' chat-open' : ''}`} role="dialog" aria-modal="true" aria-label="ARIA Live meeting"
      onKeyDown={e => { if (e.key === 'Escape') { if (confirmEnd) setConfirmEnd(false); else closeChat() } }}>
      <header className="meeting-header">
        <div className="meeting-brand"><BrandLogo className="meeting-official-logo" /><div className="meeting-brand-meta"><span>LIVE</span><small>Your financial research companion</small></div></div>
        <div className="meeting-connection"><span data-connected={state.connected} />{state.connected ? 'Connected' : state.status === 'error' ? 'Connection lost' : state.started ? 'Reconnecting' : 'Connecting'}<time aria-label="Meeting duration">{clock}</time></div>
        <button className="meeting-chats" onClick={() => window.dispatchEvent(new Event("aria:toggle-history"))} aria-label="Chat history">Chats</button>
        <button className="meeting-exit" onClick={end} aria-label="Leave meeting"><X size={19} /></button>
      </header>
      <main className="meeting-stage">
        <iframe ref={frame} src={src} title="ARIA live avatar" allow="microphone; autoplay" />
        <div className="meeting-stage-label"><span className="meeting-presence" /><strong>ARIA</strong><span>AI research assistant</span></div>
        <div className="meeting-status" role="status" data-state={state.status}>{state.label}</div>
      </main>
      <aside className="meeting-chat" id="meeting-chat" aria-label="Meeting conversation" inert={!chatOpen} aria-hidden={!chatOpen}>
        <header><BrandMark className="meeting-chat-mark" /><div><strong>Conversation</strong><small>Voice and text, together</small></div><button onClick={closeChat} aria-label="Close chat"><X size={18} /></button></header>
        <div className="meeting-messages" ref={scroll} role="log" aria-label="Conversation messages" aria-live="polite" onScroll={e => { const el = e.currentTarget; followTranscript.current = el.scrollHeight - el.scrollTop - el.clientHeight < 100 }}>
          {!history.length && !pending && <div className="meeting-empty"><BrandMark className="meeting-empty-mark" /><h2>A little clarity starts here.</h2><p>Ask a question aloud or write it below. It’s all one conversation.</p>{['Explain how a SIP works', 'Help me plan an emergency fund', 'Research a company'].map(text => <button key={text} disabled={!state.started || !state.connected} onClick={() => send(text)}>{text}<span>↗</span></button>)}</div>}
          {history.map((turn, i) => <div className="meeting-turn" key={i}><div className="meeting-message user"><small>You</small><p>{turn.query}</p></div><div className="meeting-message assistant"><small>ARIA</small><Markdown text={turn.response.response || ''} /></div></div>)}
          {pending && <div className="meeting-turn"><div className="meeting-message user"><small>You</small><p>{pending.query}</p></div><div className="meeting-message assistant"><small>ARIA</small>{pending.response ? <Markdown text={pending.response} /> : <p className="meeting-thinking">Preparing your answer…</p>}</div></div>}
        </div>
        <form className="meeting-composer" onSubmit={e => { e.preventDefault(); send() }}>
          <textarea ref={input} aria-label="Message ARIA" placeholder={state.started ? 'Ask ARIA anything…' : 'Start the meeting to chat'} value={query} maxLength={1000} rows={2}
            onChange={e => setQuery(e.target.value)} disabled={!state.started || !state.connected}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send() } }} />
          <button type="submit" aria-label="Send message" disabled={!query.trim() || !state.started || !state.connected}><Send size={18} /></button>
          <small>Enter to send · Shift + Enter for a new line</small>
        </form>
      </aside>
      {(error || syncError) && <div className="meeting-error" role="alert">{error || syncError}<button aria-label="Dismiss notification" onClick={() => { setError(''); setSyncError('') }}><X size={16} /></button></div>}
      <footer className="meeting-footer">
        <div className="meeting-controls" role="toolbar" aria-label="Meeting controls">
          <button disabled={!state.started || !state.supported || !state.connected} aria-label={state.micOn ? 'Mute microphone' : 'Unmute microphone'} aria-pressed={state.micOn} onClick={() => command('mic')} className={!state.micOn ? 'is-muted' : ''}>{state.micOn ? <Mic size={20} /> : <MicOff size={20} />}<span>{state.micOn ? 'Mic on' : 'Muted'}</span></button>
          <button className="meeting-speak" disabled={!state.started || !state.connected || (!state.supported && !state.speaking)} onClick={() => command('speak')} aria-label={state.speaking ? 'Interrupt ARIA' : state.micOn ? 'Finish speaking' : 'Start listening'}>{state.speaking ? <Square size={18} /> : <Mic size={20} />}<span>{state.speaking ? 'Interrupt' : state.micOn ? 'Send speech' : 'Speak'}</span></button>
          <span className="meeting-divider" />
          <button aria-label="Toggle captions" aria-pressed={captions} onClick={() => { command('captions', { enabled: !captions }); setCaptions(!captions) }}><Captions size={21} /><span>Captions</span></button>
          <button ref={chatButton} aria-label="Toggle chat" aria-expanded={chatOpen} aria-controls="meeting-chat" aria-pressed={chatOpen} onClick={() => chatOpen ? closeChat() : setChatOpen(true)}><MessageSquare size={20} /><span>Chat</span></button>
          <span className="meeting-divider" />
          <button className="meeting-end" aria-label="End session" onClick={end}><PhoneOff size={20} /><span>End</span></button>
        </div>
        <p>ARIA can make mistakes. Verify important financial decisions.</p>
      </footer>
      {confirmEnd && <div className="meeting-confirm" role="alertdialog" aria-modal="true" aria-labelledby="meeting-confirm-title" onKeyDown={e => {
        if (e.key === 'Tab') {
          const buttons = e.currentTarget.querySelectorAll('button')
          if (e.shiftKey && document.activeElement === buttons[0]) { e.preventDefault(); buttons[1].focus() }
          if (!e.shiftKey && document.activeElement === buttons[1]) { e.preventDefault(); buttons[0].focus() }
        }
      }}><div><h2 id="meeting-confirm-title">Leave this meeting?</h2><p>{query.trim() ? 'Your unsent message will be discarded. ' : ''}{state.processing ? 'The current answer is still being prepared. ' : ''}Completed conversation history is saved.</p><button autoFocus onClick={() => setConfirmEnd(false)}>Stay in meeting</button><button className="meeting-end" onClick={() => { command('end'); onEnd() }}>Leave meeting</button></div></div>}
    </section>, document.body)
}
