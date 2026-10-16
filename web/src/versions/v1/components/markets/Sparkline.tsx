import { useId } from 'react'

/** Hand-written SVG sparkline: polyline + soft area gradient, stroke by sign of the move. */
export function Sparkline({ points, label, width = 120, height = 36 }: { points: number[]; label: string; width?: number; height?: number }) {
  const gid = useId()
  const pts = points.filter(Number.isFinite)
  if (pts.length < 2) return <svg className="mk-spark" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${label}, no chart data`} />
  const lo = Math.min(...pts), hi = Math.max(...pts), span = hi - lo || 1
  const xy = pts.map((v, i) => `${((i / (pts.length - 1)) * width).toFixed(1)},${(height - 3 - ((v - lo) / span) * (height - 6)).toFixed(1)}`)
  const color = pts[pts.length - 1] >= pts[0] ? 'var(--up)' : 'var(--down)'
  return (
    <svg className="mk-spark" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label={`${label}, ${pts.length} points`}>
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.22" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`0,${height} ${xy.join(' ')} ${width},${height}`} fill={`url(#${gid})`} />
      <polyline points={xy.join(' ')} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  )
}
