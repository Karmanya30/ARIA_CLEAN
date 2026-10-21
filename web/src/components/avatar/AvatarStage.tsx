import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Captions, Square, Volume2, VolumeX } from 'lucide-react'
import { api } from '../../api'
import type { ChatResponse } from '../../types'
import { BrandMark } from '../brand/BrandLogo'
import { useAvatarToggle } from './avatarPrefs'
import { conciseSpoken, emotionFor } from './spoken'
import type { AvatarEngine } from './useAvatarEngine'
import './AvatarStage.css'

export interface AvatarReply { id: number; query: string; response: ChatResponse }

const LABEL: Record<string, string> = { idle: 'Ready', thinking: 'Thinking', speaking: 'Speaking', listening: 'Listening', unavailable: 'Unavailable' }

/** The spoken version of a reply: the backend's rewrite (ai/llm/spoken.py) if it answers in time, else a local short version. */
export async function spokenFor(reply: AvatarReply): Promise<string> {
  const written = String(reply.response.response ?? '')
  if (typeof reply.response.spoken === 'string' && reply.response.spoken.trim()) return conciseSpoken(reply.response.spoken, 110) // the pipeline already made it
  try {
    const timeout = new Promise<never>((_, no) => window.setTimeout(() => no(new Error('slow')), 9000))
    const { spoken } = await Promise.race([api.spokenText(reply.query, written), timeout])
    if (spoken?.trim()) return conciseSpoken(spoken, 110)
  } catch { /* offline rewrite below */ }
  return conciseSpoken(written)
}

/** The live face: canvas, state cue, captions, speak/stop controls. Speaks each new reply (when speak is on) and
 * stops when the user starts typing or recording (barge-in). */
export function AvatarStage({ engine, reply, thinking, voiceControl }: {
  engine: AvatarEngine; reply: AvatarReply | null; thinking: boolean; voiceControl?: ReactNode
}) {
  const [speakOn, setSpeakOn] = useAvatarToggle('speak')
  const [captionsOn, setCaptionsOn] = useAvatarToggle('captions')
  const [preparing, setPreparing] = useState(false)
  const [capture, setCapture] = useState('idle')
  const engineRef = useRef(engine)
  useEffect(() => { engineRef.current = engine }, [engine])
  const seen = useRef(reply?.id ?? 0) // a reply that was already there when the panel opened is not spoken again
  const prep = useRef(0)

  const interrupt = useCallback(() => {
    prep.current++
    setPreparing(false)
    engineRef.current.interrupt()
  }, [])

  // Barge-in: typing a new message or starting the microphone stops the avatar at once.
  useEffect(() => {
    const onInput = (e: Event) => { if ((e.target as Element | null)?.closest?.('.composer-input')) interrupt() }
    const onCaptureStart = () => interrupt()
    const onCaptureState = (e: Event) => { const d = (e as CustomEvent<string>).detail; setCapture(d); engineRef.current.listening(d === 'recording') }
    document.addEventListener('input', onInput)
    window.addEventListener('aria:voice-capture-start', onCaptureStart)
    window.addEventListener('aria:voice-capture-state', onCaptureState)
    return () => {
      document.removeEventListener('input', onInput)
      window.removeEventListener('aria:voice-capture-start', onCaptureStart)
      window.removeEventListener('aria:voice-capture-state', onCaptureState)
    }
  }, [interrupt])

  // Speak every new reply.
  useEffect(() => {
    if (!reply || reply.id === seen.current) return
    seen.current = reply.id
    if (!speakOn || reply.response.domain === 'error') return
    const token = ++prep.current
    setPreparing(true)
    void spokenFor(reply).then((text) => {
      if (token !== prep.current) return // interrupted or superseded while the rewrite ran
      setPreparing(false)
      if (text) engineRef.current.speak(text, emotionFor({ ...reply.response, response: String(reply.response.response ?? '') }))
    })
  }, [reply, speakOn])

  const listening = capture === 'recording' || capture === 'requesting'
  const state = listening ? 'listening' : thinking || preparing || engine.state === 'thinking' ? 'thinking'
    : engine.state === 'speaking' ? 'speaking' : 'idle'
  const busy = state === 'speaking' || state === 'thinking'

  return (
    <section className="avatar-stage" data-state={state} aria-label="ARIA live avatar" onPointerDown={engine.unlock}>
      <div className="avatar-frame">
        <canvas ref={engine.attachCanvas} className="avatar-canvas" hidden={!engine.hasFrame}
          role="img" aria-label="ARIA, an AI-generated avatar" />
        {!engine.hasFrame && (
          <div className="avatar-placeholder" aria-hidden="true">
            <BrandMark />
          </div>
        )}
        <span className="avatar-state" role="status" aria-live="polite">
          <i className="avatar-state-dot" aria-hidden="true" />
          {LABEL[state]}
        </span>
        {captionsOn && engine.caption && <p className="avatar-caption" aria-live="off">{engine.caption}</p>}
      </div>
      <div className="avatar-controls" role="group" aria-label="Avatar controls">
        <button type="button" className="avatar-btn" aria-pressed={speakOn} onClick={() => { if (speakOn) interrupt(); setSpeakOn(!speakOn) }}
          title={speakOn ? 'ARIA speaks each reply. Click to mute.' : 'Replies are silent. Click to let ARIA speak.'}>
          {speakOn ? <Volume2 size={16} aria-hidden="true" /> : <VolumeX size={16} aria-hidden="true" />}
          <span>{speakOn ? 'Speaking on' : 'Speaking off'}</span>
        </button>
        <button type="button" className="avatar-btn" onClick={interrupt} disabled={!busy} title="Stop speaking">
          <Square size={14} aria-hidden="true" /><span>Stop</span>
        </button>
        <button type="button" className="avatar-btn" aria-pressed={captionsOn} onClick={() => setCaptionsOn(!captionsOn)} title="Show captions">
          <Captions size={16} aria-hidden="true" /><span>Captions</span>
        </button>
      </div>
      {voiceControl && <div className="avatar-voice">{voiceControl}</div>}
      <p className="avatar-label">AI-generated avatar (synthetic media). Not a real person.</p>
    </section>
  )
}
