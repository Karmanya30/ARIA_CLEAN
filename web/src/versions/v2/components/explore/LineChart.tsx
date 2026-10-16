import { useEffect, useRef, useState } from 'react'
import type { IChartApi } from 'lightweight-charts'
import { fmtNum } from '../markets/format'

const withAlpha = (c: string, a: string) => (/^#[0-9a-f]{6}$/i.test(c) ? c + a : c)
/** The API may send seconds or milliseconds; the chart wants seconds, strictly increasing. */
export function cleanPoints(points: { t: number; v: number }[]): { time: number; value: number }[] {
  const out: { time: number; value: number }[] = []
  for (const p of points) {
    const time = Math.floor(p.t > 1e11 ? p.t / 1000 : p.t)
    if (!Number.isFinite(time) || !Number.isFinite(p.v)) continue
    if (out.length && time <= out[out.length - 1].time) continue
    out.push({ time, value: p.v })
  }
  return out
}

/** Single-series price/NAV area chart. Colours come from CSS variables, so it follows the theme; it is rebuilt when Light/Night flips. */
export function LineChart({ points, intraday, label, onTip }: { points: { t: number; v: number }[]; intraday: boolean; label: string; onTip: (t: string | null) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [modeTick, setModeTick] = useState(0)
  useEffect(() => {
    const mo = new MutationObserver(() => setModeTick((n) => n + 1))
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-mode', 'data-theme'] })
    return () => mo.disconnect()
  }, [])
  useEffect(() => {
    const el = ref.current
    if (!el) return
    let chart: IChartApi | undefined
    let ro: ResizeObserver | undefined
    let dead = false
    const fmt = new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', ...(intraday ? { hour: '2-digit', minute: '2-digit', hour12: false } : { year: 'numeric' }) })
    const timeFmt = (t: number) => fmt.format(new Date(t * 1000))
    import('lightweight-charts').then(({ createChart, AreaSeries, ColorType }) => {
      if (dead) return
      const cs = getComputedStyle(el)
      const v = (n: string) => cs.getPropertyValue(n).trim()
      const [up, down, ink, border, bg] = [v('--up'), v('--down'), v('--ink-muted'), v('--border'), v('--bg')]
      const calm = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      chart = createChart(el, {
        autoSize: false,
        width: el.clientWidth,
        height: el.clientHeight,
        layout: { background: { type: ColorType.Solid, color: bg }, textColor: ink, attributionLogo: true, fontSize: 11 },
        grid: { vertLines: { color: border }, horzLines: { color: border } },
        rightPriceScale: { borderColor: border },
        timeScale: { borderColor: border, timeVisible: intraday, tickMarkFormatter: (t: number) => timeFmt(t) },
        localization: { timeFormatter: timeFmt },
        kineticScroll: { mouse: !calm, touch: !calm },
      })
      const data = cleanPoints(points)
      const rising = data.length < 2 || data[data.length - 1].value >= data[0].value
      const line = rising ? up : down
      const s = chart.addSeries(AreaSeries, { lineColor: line, topColor: withAlpha(line, '40'), bottomColor: withAlpha(line, '05'), lineWidth: 2 })
      s.setData(data as never)
      chart.timeScale().fitContent()
      const byT = new Map(data.map((d) => [d.time, d.value]))
      chart.subscribeCrosshairMove((p) => {
        const val = p.time !== undefined ? byT.get(p.time as number) : undefined
        onTip(val === undefined ? null : `${timeFmt(p.time as number)}: ${fmtNum(val)}`)
      })
      ro = new ResizeObserver(() => chart?.resize(el.clientWidth, el.clientHeight))
      ro.observe(el)
    })
    return () => {
      dead = true
      ro?.disconnect()
      chart?.remove()
    }
  }, [points, intraday, onTip, modeTick])
  return <div ref={ref} className="sd-chart" role="img" aria-label={label} />
}
