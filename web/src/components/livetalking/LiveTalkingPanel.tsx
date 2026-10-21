import { useCallback, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Captions, Info, Square, Volume2, VolumeX } from 'lucide-react'
import { BrandMark } from '../brand/BrandLogo'
import { VoiceDisk } from '../chat/VoiceDisk'
import { spokenFor, type AvatarReply } from '../avatar/AvatarStage'
import { useAvatarToggle } from '../avatar/avatarPrefs'
import { useLiveTalking } from './useLiveTalking'
import '../avatar/AvatarStage.css'
import './LiveTalkingPanel.css'

const LABEL: Record<string, string> = { idle: 'Ready', connecting: 'Connecting', thinking: 'Thinking', speaking: 'Speaking', listening: 'Listening' }

/** The avatar column of LiveTalking mode: the WebRTC face from the local LiveTalking service when it is up, the ARIA disk
 * with a notice otherwise (retrying in the background). Speaks each new reply and stops on barge-in. */
export function LiveTalkingPanel({ reply, thinking, audioToken, voiceControl }: {
  reply: AvatarReply | null; thinking: boolean; audioToken?: string; voiceControl?: ReactNode
}) {
  const lt = useLiveTalking(true)
  const [speakOn, setSpeakOn] = useAvatarToggle('speak')
  const [captionsOn, setCaptionsOn] = useAvatarToggle('captions')
  const [preparing, setPreparing] = useState(false)
  const [capture, setCapture] = useState('idle')
  const [caption, setCaption] = useState('')
  const ltRef = useRef(lt)
  useEffect(() => { ltRef.current = lt }, [lt])
  const seen = useRef(reply?.id ?? 0) // a reply that was already there when the panel opened is not spoken
  const prep = useRef(0)

  const interrupt = useCallback(() => {
    prep.current++
    setPreparing(false)
    ltRef.current.interrupt()
  }, [])

  // Barge-in: typing a new message or starting the microphone stops the avatar at once.
  useEffect(() => {
    const onInput = (e: Event) => { if ((e.target as Element | null)?.closest?.('.composer-input')) interrupt() }
    const onCaptureStart = () => interrupt()
    const onCaptureState = (e: Event) => setCapture((e as CustomEvent<string>).detail)
    document.addEventListener('input', onInput)
    window.addEventListener('aria:voice-capture-start', onCaptureStart)
    window.addEventListener('aria:voice-capture-state', onCaptureState)
    return () => {
      document.removeEventListener('input', onInput)
      window.removeEventListener('aria:voice-capture-start', onCaptureStart)
      window.removeEventListener('aria:voice-capture-state', onCaptureState)
    }
  }, [interrupt])

  // Speak every new reply (only while the face is connected; otherwise the disk below speaks it).
  useEffect(() => {
    if (!reply || reply.id === seen.current) return
    seen.current = reply.id
    if (!speakOn || reply.response.domain === 'error' || ltRef.current.status !== 'ready') return
    const token = ++prep.current
    setPreparing(true)
    void spokenFor(reply).then((text) => {
      if (token !== prep.current) return // interrupted or superseded while the rewrite ran
      setPreparing(false)
      if (text) { setCaption(text); ltRef.current.speak(text) }
    })
  }, [reply, speakOn])

  const listening = capture === 'recording' || capture === 'requesting'
  const state = lt.status === 'connecting' ? 'connecting' : listening ? 'listening' : thinking || preparing ? 'thinking' : lt.speaking ? 'speaking' : 'idle'
  const busy = state === 'speaking' || state === 'thinking'

  if (lt.status === 'unavailable') {
    return (
      <>
        <p className="avatar-notice" role="status">
          <Info size={16} aria-hidden="true" />
          <span>{lt.reason ?? 'LiveTalking service is not running: start the Lip-sync GPU launcher'}. ARIA’s disk is shown meanwhile, and we will switch back once it is running.</span>
        </p>
        <VoiceDisk audioToken={audioToken} voiceControl={voiceControl} />
      </>
    )
  }
  return (
    <section className="avatar-stage" data-state={state === 'connecting' ? 'idle' : state} aria-label="ARIA LiveTalking avatar"
      onPointerDown={() => { if (lt.soundBlocked) lt.enableSound() }}>
      <div className="avatar-frame">
        <video ref={lt.attachVideo} className="avatar-canvas lt-video" autoPlay playsInline  aria-label="ARIA, an AI-generated avatar" />
        {!lt.hasFrame && (
          <div className="avatar-placeholder" aria-hidden="true"><BrandMark /></div>
        )}
        <span className="avatar-state" role="status" aria-live="polite">
          <i className="avatar-state-dot" aria-hidden="true" />
          {LABEL[state]}
        </span>
        {lt.soundBlocked && (
          <button type="button" className="lt-sound" onClick={lt.enableSound}><VolumeX size={16} aria-hidden="true" /> Click to enable sound</button>
        )}
        {captionsOn && lt.speaking && caption && <p className="avatar-caption lt-caption" aria-live="off">{caption}</p>}
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
      <p className="avatar-label">AI-generated avatar (synthetic media). Not a real person. Face: LiveTalking sample avatar</p>
    </section>
  )
}
