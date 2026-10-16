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
        className={recording ? 'voice-btn recording' : 'voice-btn'}
        onClick={recording ? stop : start}
        disabled={busy}
        title={recording ? 'Stop recording' : 'Ask ARIA by voice'}
      >
        {recording ? <Square size={16} /> : <Mic size={16} />}
        {busy ? 'Transcribing…' : recording ? 'Stop' : 'Ask by voice'}
      </button>
      {error && <span className="voice-error">{error}</span>}
    </div>
  )
}
