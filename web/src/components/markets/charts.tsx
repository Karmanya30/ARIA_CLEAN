/** Tiny hand-written SVG helpers shared by the Markets panels (no chart library needed for these). */
export function polar(cx: number, cy: number, r: number, deg: number): [number, number] {
  const a = ((deg - 90) * Math.PI) / 180
  return [cx + r * Math.cos(a), cy + r * Math.sin(a)]
}

/** Arc path from deg a0 to a1 (clockwise from 12 o'clock). A full circle is capped just under 360 so it still draws. */
export function arc(cx: number, cy: number, r: number, a0: number, a1: number): string {
  const end = Math.min(a1, a0 + 359.99)
  const [x0, y0] = polar(cx, cy, r, a0)
  const [x1, y1] = polar(cx, cy, r, end)
  return `M${x0.toFixed(2)} ${y0.toFixed(2)}A${r} ${r} 0 ${end - a0 > 180 ? 1 : 0} 1 ${x1.toFixed(2)} ${y1.toFixed(2)}`
}

/** Score ring: track + arc, centre text is supplied by the caller as children. */
export function Ring({ value, max = 100, size = 96, stroke = 10, label, children }: { value: number; max?: number; size?: number; stroke?: number; label: string; children?: React.ReactNode }) {
  const c = size / 2
  const r = c - stroke / 2
  const frac = Math.max(0, Math.min(1, value / max))
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} role="img" aria-label={label} style={{ flex: 'none' }}>
      <circle cx={c} cy={c} r={r} fill="none" stroke="var(--bg-inset)" strokeWidth={stroke} />
      {frac > 0 && <path d={arc(c, c, r, 0, frac * 360)} fill="none" stroke="var(--accent)" strokeWidth={stroke} strokeLinecap="round" />}
      {children}
    </svg>
  )
}
