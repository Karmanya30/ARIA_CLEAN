import { useEffect, useRef, useState } from 'react'
import { Send, User } from 'lucide-react'
import { api } from '../../api'
import type { ChatMode, HistoryTurn } from '../../types'
import { useTavusSession } from '../../hooks/useTavusSession'
import { TemplateCards } from './TemplateCards'
import { MessageBubble } from './MessageBubble'
import { VoiceRecorder } from './VoiceRecorder'
import { TavusVideo } from './TavusVideo'
import { TavusTranscript } from './TavusTranscript'
import { ContextStrip } from './ContextStrip'
import { ThinkingStatus } from './ThinkingStatus'
import { ConversationalAvatar } from './ConversationalAvatar'
import './ChatTab.css'

const MODES: ChatMode[] = ['Normal Mode', 'Conversational Mode', 'Live Avatar (Free)', 'Tavus CVI Mode (WebRTC)']

function greeting(): string {
  const hour = new Date().getHours()
  if (hour < 12) return 'Good morning'
  if (hour < 17) return 'Good afternoon'
  return 'Good evening'
}

function Composer({
  variant,
  query,
  onQueryChange,
  onSubmit,
  disabled,
}: {
  variant: 'centered' | 'pinned'
  query: string
  onQueryChange: (v: string) => void
  onSubmit: () => void
  disabled: boolean
}) {
  return (
    <div className={`composer composer-${variant}`}>
      <VoiceRecorder onTranscribed={onQueryChange} />
      <input
        aria-label="Message ARIA"
        className="input composer-input"
        placeholder="Message ARIA…"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') onSubmit()
        }}
      />
      <button className="btn btn-primary composer-submit" onClick={onSubmit} disabled={disabled || !query.trim()} type="button" aria-label="Send message">
        <Send size={15} />
      </button>
    </div>
  )
}

export function ChatTab({ sessionId, onOpenProfile }: { sessionId: string; onOpenProfile?: () => void }) {
  const [mode, setMode] = useState<ChatMode>('Normal Mode')
  const [history, setHistory] = useState<HistoryTurn[]>([])
  const [query, setQuery] = useState('')
  const [sending, setSending] = useState(false)
  // The message being answered: shown at once, so pressing Send visibly does something even on the first
  // message (the hero used to stay unchanged until the reply arrived, which looked like a dead button).
  const [pending, setPending] = useState<string | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  const isTavus = mode === 'Tavus CVI Mode (WebRTC)'
  const isConversational = mode === 'Conversational Mode'
  // Free streaming voice mode (api/routes/live.py + interface/avatar/live.html): the call UI lives in the iframe,
  // and its turns are saved to the same session history this column shows.
  const isLive = mode === 'Live Avatar (Free)'
  const showHero = history.length === 0 && !isTavus && !pending
  // Hooks can't be called conditionally, so this always runs -- `enabled`
  // is what actually gates starting/ending the paid call.
  const tavusSession = useTavusSession(sessionId, isTavus)

  useEffect(() => {
    api.getHistory(sessionId).then((res) => setHistory(res.history as HistoryTurn[]))
  }, [sessionId])

  useEffect(() => {
    if (!isLive) return
    const refresh = () => api.getHistory(sessionId).then((res) => setHistory(res.history as HistoryTurn[])).catch(() => {})
    const onMessage = (ev: MessageEvent) => {
      if (ev.data?.source === 'aria-live' && ev.data.type === 'done') refresh()
    }
    window.addEventListener('message', onMessage)
    const poll = setInterval(refresh, 4000)
    return () => {
      window.removeEventListener('message', onMessage)
      clearInterval(poll)
    }
  }, [isLive, sessionId])

  // The message list is the only part of the page that scrolls (the
  // avatar/video stage above it stays fixed in place) -- so unlike a
  // normal page, a new turn doesn't automatically come into view on its
  // own; keep the scroll pinned to the latest message.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [history.length, sending])

  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || sending) return
    setSending(true)
    setPending(trimmed)
    setQuery('')
    try {
      const response = await api.sendMessage(trimmed, sessionId, mode)
      setHistory((h) => [...h, { query: trimmed, response, audio_token: response.audio_token }])
    } catch (err) {
      setHistory((h) => [
        ...h,
        {
          query: trimmed,
          response: { domain: 'error', query: trimmed, response: `Error: ${err instanceof Error ? err.message : 'request failed'}` },
        },
      ])
    } finally {
      setSending(false)
      setPending(null)
    }
  }

  async function clearChat() {
    await api.clearChat(sessionId)
    setHistory([])
    if (isTavus) setMode('Normal Mode')
  }

  function markQuizAnswered(index: number, correct: boolean) {
    setHistory((h) => h.map((t, i) => (i === index ? { ...t, quiz_answered: true, quiz_correct: correct } : t)))
  }

  const financeTurns = history.filter((t) => t.response.domain === 'finance').length
  const latestAudioToken = [...history].reverse().find((t) => t.audio_token)?.audio_token ?? undefined
  // Conversational/Tavus modes have a real avatar or video to show, so
  // they get a large dedicated left column for it -- "large view" was
  // the specific ask. Normal Mode has nothing to put there (just the
  // small decorative orb during its own idle state), so it keeps the
  // simpler single centered column instead of wasting half the screen
  // on empty space.
  const isSplitLayout = isTavus || isConversational || isLive

  const pendingTurn = pending && (
    <div className="message-pair">
      <div className="bubble bubble-user">
        <span className="bubble-avatar">
          <User size={15} />
        </span>
        <p>{pending}</p>
      </div>
      <ThinkingStatus />
    </div>
  )

  const topbar = (
    <div className="chat-topbar">
      <select
        id="chat-mode"
        aria-label="Mode"
        className="input chat-mode-select"
        value={mode}
        onChange={(e) => setMode(e.target.value as ChatMode)}
      >
        {MODES.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
      <button className="btn" onClick={clearChat} type="button">
        Clear Chat
      </button>
    </div>
  )

  if (isSplitLayout) {
    return (
      <div className="chat-page chat-page-split">
        <h1 className="sr-only">ARIA chat</h1>
        {topbar}
        <div className="chat-split-body">
          <div className="chat-avatar-col">
            {isTavus && <TavusVideo session={tavusSession} />}
            {isConversational && <ConversationalAvatar audioToken={latestAudioToken} />}
            {isLive && (
              <iframe
                className="live-avatar-frame"
                src={`/avatar/live?session_id=${encodeURIComponent(sessionId)}`}
                allow="microphone; autoplay"
                title="ARIA live avatar"
              />
            )}
          </div>
          <div className="chat-chat-col">
            <div className="chat-scroll-region" ref={scrollRef}>
              {isTavus ? (
                <TavusTranscript session={tavusSession} />
              ) : (
                <div className="chat-thread">
                  {history.length === 0 && (
                    <p className="chat-empty-hint">
                      {isLive ? 'Press “Start conversation” on the avatar, then speak or type. The conversation appears here.' : 'Ask ARIA something to get started.'}
                    </p>
                  )}
                  {history.map((turn, i) => (
                    <MessageBubble
                      key={i}
                      turn={turn}
                      sessionId={sessionId}
                      onQuizAnswered={(correct) => markQuizAnswered(i, correct)}
                  onRetry={sending ? undefined : send}
                  onAsk={sending ? undefined : send}
                  isLast={i === history.length - 1 && !pending}
                  onOpenProfile={onOpenProfile}
                    />
                  ))}
                  {pendingTurn}
                </div>
              )}
            </div>
            {!isTavus && !isLive && (
              <Composer variant="pinned" query={query} onQueryChange={setQuery} onSubmit={() => send(query)} disabled={sending} />
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="chat-page">
      <h1 className="sr-only">ARIA chat</h1>
      {topbar}

      {showHero && (
        <div className="chat-stage">
          <div className="hero-orb" />
        </div>
      )}

      {showHero ? (
        <div className="chat-idle-block">
          <div className="chat-idle-inner">
            <div className="chat-hero-text">
              <h2>{greeting()} — what can I help with?</h2>
              <p>Ask about your finances, learn a concept, or check the market. ARIA routes it to the right module automatically.</p>
            </div>
            <ContextStrip refreshKey={financeTurns} onOpenProfile={onOpenProfile} />
            <Composer variant="centered" query={query} onQueryChange={setQuery} onSubmit={() => send(query)} disabled={sending} />
            <TemplateCards onPick={send} />
          </div>
        </div>
      ) : (
        <>
          <div className="chat-scroll-region" ref={scrollRef}>
            <div className="chat-thread">
              {history.map((turn, i) => (
                <MessageBubble
                  key={i}
                  turn={turn}
                  sessionId={sessionId}
                  onQuizAnswered={(correct) => markQuizAnswered(i, correct)}
                  onRetry={sending ? undefined : send}
                  onAsk={sending ? undefined : send}
                  isLast={i === history.length - 1 && !pending}
                  onOpenProfile={onOpenProfile}
                />
              ))}
              {pendingTurn}
            </div>
          </div>
          <ContextStrip refreshKey={financeTurns} onOpenProfile={onOpenProfile} />
          <Composer variant="pinned" query={query} onQueryChange={setQuery} onSubmit={() => send(query)} disabled={sending} />
        </>
      )}
    </div>
  )
}
