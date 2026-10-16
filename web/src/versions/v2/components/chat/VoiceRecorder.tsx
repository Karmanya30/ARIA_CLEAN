import { useRef, useState } from 'react'
import { Mic, Square } from 'lucide-react'
import { api } from '../../api'
import './VoiceRecorder.css'

export function VoiceRecorder({ onTranscribed }: { onTranscribed: (text: string) => void }) {
  const [recording, setRecording] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])

  async function start() {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const recorder = new MediaRecorder(stream)
      chunksRef.current = []
      recorder.ondataavailable = (e) => chunksRef.current.push(e.data)
      recorder.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunksRef.current, { type: 'audio/webm' })
        setBusy(true)
        try {
          const { text } = await api.transcribe(blob)
          if (text) onTranscribed(text)
          else setError('Could not transcribe the audio.')
        } catch (err) {
          setError(err instanceof Error ? err.message : 'Transcription failed.')
        } finally {
          setBusy(false)
        }
      }
      recorder.start()
      recorderRef.current = recorder
      setRecording(true)
    } catch {
      setError('Microphone access was denied or unavailable.')
    }
  }

  function stop() {
    recorderRef.current?.stop()
    setRecording(false)
  }

  return (
    <div className="voice-recorder">
      <button
        type="button"
        className={`voice-btn${recording ? ' recording' : ''}${busy ? ' busy' : ''}`}
        onClick={recording ? stop : start}
        disabled={busy}
        title={busy ? 'Transcribing…' : recording ? 'Stop recording' : 'Ask ARIA by voice'}
        aria-label={busy ? 'Transcribing' : recording ? 'Stop recording' : 'Record voice message'}
      >
        {recording ? (
          <>
            <Square size={14} />
            {/* Waveform bars */}
            <span className="voice-wave" aria-hidden="true">
              {[1, 2, 3, 4, 5].map((i) => (
                <span key={i} className="voice-bar" style={{ animationDelay: `${(i - 1) * 90}ms` }} />
              ))}
            </span>
          </>
        ) : busy ? (
          <span className="voice-spinner" aria-hidden="true" />
        ) : (
          <Mic size={16} />
        )}
      </button>
      {error && <span className="voice-error">{error}</span>}
    </div>
  )
}
