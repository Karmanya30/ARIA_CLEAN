import { useEffect, useRef, useState, useCallback } from 'react'
import './NormalModeOrb.css'

/** Number of frequency bars rendered around the orb */
const BAR_COUNT = 40

function useAudioAnalyser(audioRef: React.RefObject<HTMLAudioElement | null>) {
  const ctxRef = useRef<AudioContext | null>(null)
  const sourceRef = useRef<MediaElementAudioSourceNode | null>(null)
  const analyserRef = useRef<AnalyserNode | null>(null)

  const setup = useCallback((el: HTMLAudioElement) => {
    if (sourceRef.current) return
    const ctx = new AudioContext()
    const analyser = ctx.createAnalyser()
    analyser.fftSize = 128
    analyser.smoothingTimeConstant = 0.82
    const source = ctx.createMediaElementSource(el)
    source.connect(analyser)
    analyser.connect(ctx.destination)
    ctxRef.current = ctx
    sourceRef.current = source
    analyserRef.current = analyser
  }, [])

  useEffect(() => {
    const el = audioRef.current
    if (!el) return
    const onPlay = () => {
      if (ctxRef.current?.state === 'suspended') ctxRef.current.resume()
      setup(el)
    }
    el.addEventListener('play', onPlay)
    return () => el.removeEventListener('play', onPlay)
  }, [audioRef, setup])

  return analyserRef
}

function lerp(a: number, b: number, t: number) {
  return a + (b - a) * t
}

interface NormalModeOrbProps {
  speaking: boolean
  audioRef?: React.RefObject<HTMLAudioElement | null>
}

export function NormalModeOrb({ speaking, audioRef }: NormalModeOrbProps) {
  const wrapRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const rafRef = useRef<number>(0)
  const barsRef = useRef<Float32Array>(new Float32Array(BAR_COUNT).fill(0))
  const scaleRef = useRef(1)
  const dummyAudioRef = useRef<HTMLAudioElement | null>(null)

  const effectiveAudioRef = (audioRef ?? dummyAudioRef) as React.RefObject<HTMLAudioElement | null>
  const analyserRef = useAudioAnalyser(effectiveAudioRef)

  const [isSpeaking, setIsSpeaking] = useState(false)

  useEffect(() => {
    if (speaking) {
      setIsSpeaking(true)
    } else {
      const t = setTimeout(() => setIsSpeaking(false), 600)
      return () => clearTimeout(t)
    }
  }, [speaking])

  // Auto-resize canvas pixel buffer to match CSS size (handles compact <-> idle transition)
  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return
    const ro = new ResizeObserver(() => {
      const { offsetWidth: w, offsetHeight: h } = wrap
      if (w > 0 && h > 0) {
        canvas.width = w
        canvas.height = h
      }
    })
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')!

    let phase = 0

    function draw() {
      rafRef.current = requestAnimationFrame(draw)
      const W = canvas!.width
      const H = canvas!.height
      if (!W || !H) return
      ctx.clearRect(0, 0, W, H)

      const cx = W / 2
      const cy = H / 2
      const orbR = Math.min(W, H) * 0.32

      // Frequency data
      const analyser = analyserRef.current
      let freqData: Uint8Array<ArrayBuffer> | null = null
      if (analyser) {
        freqData = new Uint8Array(analyser.frequencyBinCount)
        analyser.getByteFrequencyData(freqData)
      }

      // Build target bar heights
      const targetBars = new Float32Array(BAR_COUNT)
      if (freqData && isSpeaking) {
        for (let i = 0; i < BAR_COUNT; i++) {
          const bin = Math.floor((i / BAR_COUNT) * freqData.length)
          targetBars[i] = freqData[bin] / 255
        }
      } else if (isSpeaking) {
        // Fallback synthetic wave
        phase += 0.06
        for (let i = 0; i < BAR_COUNT; i++) {
          const t = (i / BAR_COUNT) * Math.PI * 2
          targetBars[i] =
            0.3 +
            0.4 * Math.abs(Math.sin(t * 2 + phase)) +
            0.2 * Math.abs(Math.sin(t * 3 - phase * 0.7))
        }
      } else {
        // Idle gentle undulation
        phase += 0.015
        for (let i = 0; i < BAR_COUNT; i++) {
          const t = (i / BAR_COUNT) * Math.PI * 2
          targetBars[i] = 0.06 + 0.07 * Math.abs(Math.sin(t + phase))
        }
      }

      for (let i = 0; i < BAR_COUNT; i++) {
        barsRef.current[i] = lerp(barsRef.current[i], targetBars[i], 0.22)
      }

      const avgAmp = barsRef.current.reduce((s, v) => s + v, 0) / BAR_COUNT
      const targetScale = isSpeaking ? 1 + avgAmp * 0.18 : 1
      scaleRef.current = lerp(scaleRef.current, targetScale, 0.1)
      const s = scaleRef.current

      // Draw frequency bars
      const gapDeg = 360 / BAR_COUNT
      const maxBarH = orbR * 0.7
      const minBarH = orbR * 0.04

      for (let i = 0; i < BAR_COUNT; i++) {
        const angleDeg = i * gapDeg - 90
        const angleRad = (angleDeg * Math.PI) / 180
        const barH = minBarH + barsRef.current[i] * maxBarH
        const inner = orbR * s + 8
        const outer = inner + barH

        const x1 = cx + Math.cos(angleRad) * inner
        const y1 = cy + Math.sin(angleRad) * inner
        const x2 = cx + Math.cos(angleRad) * outer
        const y2 = cy + Math.sin(angleRad) * outer

        const progress = i / BAR_COUNT
        const hue = 220 + progress * 160
        const alpha = 0.35 + barsRef.current[i] * 0.65
        const lineW = isSpeaking ? 2.5 + barsRef.current[i] * 2.5 : 1.5

        ctx.save()
        ctx.beginPath()
        ctx.moveTo(x1, y1)
        ctx.lineTo(x2, y2)
        ctx.strokeStyle = `hsla(${hue}, 80%, 65%, ${alpha})`
        ctx.lineWidth = lineW
        ctx.lineCap = 'round'
        ctx.shadowColor = `hsla(${hue}, 90%, 70%, 0.6)`
        ctx.shadowBlur = isSpeaking ? 8 : 3
        ctx.stroke()
        ctx.restore()
      }

      // Draw glow halo
      const glowR = orbR * s * (isSpeaking ? 1.35 + avgAmp * 0.4 : 1.1)
      const glow = ctx.createRadialGradient(cx, cy, orbR * s * 0.5, cx, cy, glowR)
      glow.addColorStop(0, `rgba(41,83,184,${isSpeaking ? 0.25 + avgAmp * 0.3 : 0.10})`)
      glow.addColorStop(0.5, `rgba(124,111,219,${isSpeaking ? 0.15 + avgAmp * 0.2 : 0.06})`)
      glow.addColorStop(1, 'rgba(62,207,142,0)')
      ctx.save()
      ctx.beginPath()
      ctx.arc(cx, cy, glowR, 0, Math.PI * 2)
      ctx.fillStyle = glow
      ctx.fill()
      ctx.restore()
    }

    draw()
    return () => cancelAnimationFrame(rafRef.current)
  }, [analyserRef, isSpeaking])

  return (
    <div ref={wrapRef} className={`norb-wrap${isSpeaking ? ' norb-speaking' : ''}`} aria-hidden="true">
      <canvas ref={canvasRef} className="norb-canvas" />
      <div className={`hero-orb norb-orb${isSpeaking ? ' orb-speaking' : ''}`} />
    </div>
  )
}
