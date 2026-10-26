import { useEffect, useRef, useState } from 'react'
import { Mic, Square } from 'lucide-react'
import { api } from '../../api'
import './VoiceRecorder.css'

type Phase = 'idle' | 'requesting' | 'recording' | 'transcribing'

export function VoiceRecorder({ onTranscribed, disabled = false, conversational = false, onBusyChange }: {
  onTranscribed: (text: string) => void | Promise<void>; disabled?: boolean; conversational?: boolean; onBusyChange?: (busy: boolean) => void
}) {
  const [phase, setPhase] = useState<Phase>('idle')
  const [error, setError] = useState<string | null>(null)
  const current = useRef<Phase>('idle')
  const generation = useRef(0)
  const recorder = useRef<MediaRecorder | null>(null)
  const stream = useRef<MediaStream | null>(null)
  const transcription = useRef<AbortController | null>(null)
  const callback = useRef(onTranscribed)
  useEffect(() => { callback.current = onTranscribed }, [onTranscribed])
  useEffect(() => { onBusyChange?.(phase !== 'idle') }, [phase, onBusyChange])
  useEffect(() => {
    if (conversational) window.dispatchEvent(new CustomEvent('aria:voice-capture-state', { detail: phase }))
  }, [phase, conversational])
  const changePhase = (next: Phase) => { current.current = next; setPhase(next) }
  const releaseMic = () => { stream.current?.getTracks().forEach(track => track.stop()); stream.current = null }

  useEffect(() => () => {
    generation.current++
    transcription.current?.abort()
    const active = recorder.current
    if (active) {
      active.onstop = null
      active.ondataavailable = null
      active.onerror = null
      if (active.state !== 'inactive') active.stop()
    }
    stream.current?.getTracks().forEach(track => track.stop())
  }, [])

  async function toggle() {
    if (current.current === 'transcribing' || (disabled && current.current === 'idle')) return
    if (current.current === 'requesting') {
      generation.current++
      changePhase('idle')
      return
    }
    if (current.current === 'recording') {
      changePhase('transcribing')
      if (recorder.current?.state !== 'inactive') recorder.current?.stop()
      releaseMic()
      return
    }
    const request = ++generation.current
    setError(null)
    changePhase('requesting')
    // Unlock reply playback on the click and stop ARIA speaking into the mic.
    if (conversational) window.dispatchEvent(new Event('aria:voice-capture-start'))
    try {
      const input = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (request !== generation.current) { input.getTracks().forEach(track => track.stop()); return }
      stream.current = input
      const mime = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type))
      const active = new MediaRecorder(input, mime ? { mimeType: mime } : undefined)
      recorder.current = active
      const chunks: Blob[] = []
      let bytes = 0
      active.ondataavailable = event => {
        bytes += event.data.size
        if (bytes > 10 * 1024 * 1024) {
          generation.current++
          active.onstop = null
          if (active.state !== 'inactive') active.stop()
          releaseMic()
          changePhase('idle')
          setError('Recording is too large. Please try a shorter question.')
        } else if (event.data.size) chunks.push(event.data)
      }
      active.onerror = () => {
        generation.current++
        active.onstop = null
        if (active.state !== 'inactive') active.stop()
        releaseMic()
        changePhase('idle')
        setError('Recording failed. Please try again.')
      }
      active.onstop = async () => {
        releaseMic()
        if (request !== generation.current) return
        changePhase('transcribing')
        const abort = new AbortController()
        transcription.current = abort
        try {
          const blob = new Blob(chunks, { type: active.mimeType || mime || 'audio/webm' })
          if (!blob.size) throw new Error('No audio was recorded. Please try again.')
          const { text } = await api.transcribe(blob, abort.signal)
          if (request !== generation.current) return
          if (!text.trim()) throw new Error('Could not hear a question. Please try again.')
          await callback.current(text.trim())
        } catch (failure) {
          if (request === generation.current && !abort.signal.aborted)
            setError(failure instanceof Error ? failure.message : 'Transcription failed.')
        } finally {
          if (request === generation.current) { transcription.current = null; changePhase('idle') }
        }
      }
      active.start(1000)
      changePhase('recording')
    } catch {
      if (request !== generation.current) return
      releaseMic()
      changePhase('idle')
      setError('Microphone access was denied or unavailable. Allow microphone access and try again.')
    }
  }

  const listening = phase === 'requesting' || phase === 'recording'
  const label = phase === 'transcribing' ? 'Transcribing' : listening ? 'Stop listening' : conversational ? 'Start listening' : 'Record voice message'
  return <div className="voice-recorder">
    <button type="button" className={`voice-btn${listening ? ' recording' : ''}${phase === 'transcribing' ? ' busy' : ''}`}
      onClick={() => void toggle()} disabled={phase === 'transcribing' || (disabled && !listening)}
      aria-label={label} aria-pressed={listening} title={label}>
      {listening ? <Square size={16} /> : phase === 'transcribing' ? <span className="voice-spinner" aria-hidden="true" /> : <Mic size={16} />}
      {conversational && <span>{phase === 'transcribing' ? 'Working…' : listening ? 'Stop listening' : 'Speak'}</span>}
    </button>
    {error && <span className="voice-error" role="alert">{error}</span>}
  </div>
}
