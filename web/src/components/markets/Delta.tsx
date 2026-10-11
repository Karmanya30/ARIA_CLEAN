import { fmtNum } from './format'

/** Signed change with an arrow, so direction never relies on colour alone. */
export function Delta({ value, suffix = '%', digits = 2, showSign = true }: { value: number; suffix?: string; digits?: number; showSign?: boolean }) {
  const dir = !Number.isFinite(value) || Number(value.toFixed(digits)) === 0 ? 'flat' : value > 0 ? 'up' : 'down'
  const text = Number.isFinite(value) ? fmtNum(Math.abs(value), digits) : '–'
  const sign = dir === 'flat' || !showSign ? '' : dir === 'up' ? '+' : '−'
  const unit = suffix === '%' ? 'percent' : suffix.trim()
  return (
    <span className={`num mk-${dir}`} role="img" aria-label={dir === 'flat' ? 'unchanged' : `${dir} ${text} ${unit}`}>
      {dir === 'up' ? '▲' : dir === 'down' ? '▼' : '–'} {sign}{text}{suffix}
    </span>
  )
}
