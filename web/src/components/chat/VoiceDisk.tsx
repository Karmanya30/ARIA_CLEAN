import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { api } from '../../api'
import { BrandMark } from '../brand/BrandLogo'
import './ConversationalAvatar.css'
import './VoiceDisk.css'

/** Uses the same audio element for audible speech and its measured visualization. */
export function VoiceDisk({ audioToken, voiceControl }: { audioToken?: string; voiceControl?: ReactNode }) {
  const audioRef = useRef<HTMLAudioElement>(null)
  const stageRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const graph = useRef<{ context: AudioContext; analyser: AnalyserNode; source: MediaElementAudioSourceNode } | null>(null)
  const [status, setStatus] = useState('Ready to talk')
  const [capturePhase, setCapturePhase] = useState('idle')

  const prepareAnalysis = useCallback(() => {
    const audio = audioRef.current
    if (!audio) return
    try {
      if (!graph.current) {
        const context = new AudioContext()
        const analyser = context.createAnalyser()
        analyser.fftSize = 2048
        analyser.smoothingTimeConstant = 0.72
        const source = context.createMediaElementSource(audio)
        source.connect(analyser)
        analyser.connect(context.destination)
        graph.current = { context, analyser, source }
      }
    } catch {
      setStatus('Voice visualization unavailable')
    }
  }, [])

  // Connect before playback: changing the output route in a play event can
  // interrupt Chromium's media stream, particularly around seeks/autoplay.
  useLayoutEffect(prepareAnalysis, [prepareAnalysis])

  useEffect(() => {
    const prepareReply = () => {
      audioRef.current?.pause()
      void graph.current?.context.resume().catch(() => {})
    }
    window.addEventListener('aria:voice-capture-start', prepareReply)
    const captureState = (event: Event) => setCapturePhase((event as CustomEvent<string>).detail)
    window.addEventListener('aria:voice-capture-state', captureState)
    return () => {
      window.removeEventListener('aria:voice-capture-start', prepareReply)
      window.removeEventListener('aria:voice-capture-state', captureState)
    }
  }, [])

  const startAnalysis = useCallback(() => {
    prepareAnalysis()
    if (!graph.current) { setStatus('Voice playing · visualization unavailable'); return }
    void graph.current.context.resume().catch(() => setStatus('Press play to enable voice'))
    setStatus('ARIA is speaking')
  }, [prepareAnalysis])

  useEffect(() => {
    const stage = stageRef.current
    const canvas = canvasRef.current
    if (!stage || !canvas) return
    const painter = canvas.getContext('2d')
    if (!painter) return
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)')
    const bins = new Uint8Array(1024)
    const wave = new Float32Array(2048)
    let frame = 0
    let energy = 0
    let size = 0
    const resize = new ResizeObserver(() => {
      size = canvas.clientWidth
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.round(size * ratio)
      canvas.height = Math.round(size * ratio)
      painter.setTransform(ratio, 0, 0, ratio, 0, 0)
    })
    resize.observe(canvas)
    function draw() {
      frame = requestAnimationFrame(draw)
      const audio = audioRef.current
      const active = !!audio && !audio.paused && !audio.ended && audio.readyState >= 2
      const current = graph.current
      let rms = 0
      let centroid = 0
      bins.fill(0)
      wave.fill(0)
      if (current && active) {
        current.analyser.getFloatTimeDomainData(wave)
        current.analyser.getByteFrequencyData(bins)
        let weight = 0
        let weightedFrequency = 0
        for (const sample of wave) rms += sample * sample
        rms = Math.sqrt(rms / wave.length)
        for (let i = 1; i < bins.length; i++) {
          weight += bins[i]
          weightedFrequency += bins[i] * i * current.context.sampleRate / 2048
        }
        centroid = weight ? weightedFrequency / weight : 0
      }
      energy += (Math.min(rms * 4, 1) - energy) * (active ? 0.22 : 0.16)
      stage!.style.setProperty('--voice-level', energy.toFixed(4))
      stage!.style.setProperty('--voice-scale', String(reduced.matches ? 1 : 1 + energy * 0.14))
      stage!.style.setProperty('--voice-turn', `${reduced.matches ? 0 : Math.min(centroid / 100, 45)}deg`)
      // Measured values also make silent/paused state observable in browser checks.
      stage!.dataset.rms = rms.toFixed(5)
      stage!.dataset.centroid = centroid.toFixed(1)
      stage!.dataset.playing = String(active)
      painter!.clearRect(0, 0, size, size)
      if (!size) return
      const center = size / 2
      const radius = size * 0.32
      painter!.lineCap = 'round'
      for (let i = 0; i < 64; i++) {
        const angle = i / 64 * Math.PI * 2 - Math.PI / 2
        const hz = 80 * Math.pow(100, i / 63)
        const index = current ? Math.min(bins.length - 1, Math.round(hz * 2048 / current.context.sampleRate)) : 0
        const strength = bins[index] / 255
        const length = 2 + strength * size * 0.1
        painter!.strokeStyle = `hsla(${160 + i * 1.7}, 75%, 60%, ${0.25 + strength * 0.7})`
        painter!.lineWidth = Math.max(1.5, size / 180)
        painter!.beginPath()
        painter!.moveTo(center + Math.cos(angle) * radius, center + Math.sin(angle) * radius)
        painter!.lineTo(center + Math.cos(angle) * (radius + length), center + Math.sin(angle) * (radius + length))
        painter!.stroke()
      }
      painter!.beginPath()
      painter!.strokeStyle = 'rgba(89, 217, 197, .7)'
      painter!.lineWidth = 1.5
      for (let i = 0; i <= 256; i++) {
        const angle = i / 256 * Math.PI * 2
        const r = size * 0.445 + wave[(i * 7) % wave.length] * size * 0.08
        const x = center + Math.cos(angle) * r
        const y = center + Math.sin(angle) * r
        if (i === 0) painter!.moveTo(x, y)
        else painter!.lineTo(x, y)
      }
      painter!.closePath()
      painter!.stroke()
    }
    draw()
    return () => {
      cancelAnimationFrame(frame)
      resize.disconnect()
      const current = graph.current
      graph.current = null
      if (current) {
        current.source.disconnect()
        current.analyser.disconnect()
        void current.context.close().catch(() => {})
      }
    }
  }, [])

  return <section className="voice-disk-panel" aria-label="ARIA conversational voice">
    <div className="voice-disk-stage" ref={stageRef} data-playing="false">
      <canvas ref={canvasRef} aria-hidden="true" />
      <div className="hero-orb voice-disk"><BrandMark /></div>
    </div>
    <p className="voice-disk-status" role="status">{capturePhase === 'requesting' ? 'Opening microphone…'
      : capturePhase === 'recording' ? 'Listening…'
      : capturePhase === 'transcribing' ? 'Preparing your reply…'
      : audioToken ? status : 'Ready to talk'}</p>
    {voiceControl && <div className="voice-disk-controls">{voiceControl}</div>}
    <p className="voice-disk-caption">{voiceControl ? 'Click Speak to listen. Click again to stop and get a reply.' : 'Voice volume shapes the disk. Frequencies shape the waves.'}</p>
    <audio ref={audioRef} controls autoPlay hidden={!audioToken} src={audioToken ? api.audioUrl(audioToken) : undefined}
      aria-label="ARIA voice playback" onPlay={startAnalysis}
      onPause={event => setStatus(event.currentTarget.ended || event.currentTarget.currentTime >= event.currentTarget.duration
        ? 'Ready to talk' : 'Voice paused')} onEnded={() => setStatus('Ready to talk')}
      onEmptied={() => setStatus('Ready to talk')}
      onError={() => setStatus('Voice unavailable. You can still read the reply.')} />
  </section>
}
