import { useEffect, useReducer } from 'react'

export type ThemeId = 'classic' | 'vitara' | 'vitara-markets' | 'vitara-clear'

export const THEMES: { id: ThemeId; label: string; blurb: string }[] = [
  { id: 'classic', label: 'Classic', blurb: 'The original ARIA look: left sidebar, cool blue accent, compact cards.' },
  {
    id: 'vitara',
    label: 'Vitara',
    blurb: 'Warm ivory canvas, top navigation bar, rounded pill controls and a deep green accent.',
  },
  { id: 'vitara-markets', label: 'Vitara Markets', blurb: 'Vitara with a live markets dashboard, ticker tape and charts.' },
  {
    id: 'vitara-clear',
    label: 'Vitara Clear',
    blurb: 'A calmer, clearer Vitara: roomier type and spacing, higher contrast, gentle motion, search up front and a night mode.',
  },
]

/** Themes that show the Markets tab and the Light/Night switch. */
export const hasMarkets = (id: ThemeId) => id === 'vitara-markets' || id === 'vitara-clear'

// index.html applies the saved value before first paint (no flash) -- keep the key in sync there.
const KEY = 'aria_theme'

export function getTheme(): ThemeId {
  try {
    const saved = localStorage.getItem(KEY)
    return THEMES.find((t) => t.id === saved)?.id ?? 'classic'
  } catch {
    return 'classic'
  }
}

export function setTheme(id: ThemeId) {
  document.documentElement.dataset.theme = id
  try {
    localStorage.setItem(KEY, id)
  } catch {
    // Storage blocked (private window etc.): the choice still applies until the tab is closed.
  }
}

// ── Colour mode (Vitara Markets and Vitara Clear; the CSS rules are scoped to those themes) ──────────────
// 'auto' follows the OS preference live. index.html applies the saved setting before first paint.
export type ModeSetting = 'light' | 'night' | 'auto'
export const MODES: { id: ModeSetting; label: string }[] = [
  { id: 'light', label: 'Light' },
  { id: 'night', label: 'Night' },
  { id: 'auto', label: 'Auto' },
]
const MODE_KEY = 'aria_mode'
const dark = window.matchMedia('(prefers-color-scheme: dark)')

export function getModeSetting(): ModeSetting {
  try {
    const saved = localStorage.getItem(MODE_KEY)
    return MODES.find((m) => m.id === saved)?.id ?? 'light'
  } catch {
    return 'light'
  }
}

const resolve = (m: ModeSetting) => (m === 'auto' ? (dark.matches ? 'night' : 'light') : m)

export function setModeSetting(m: ModeSetting) {
  document.documentElement.dataset.mode = resolve(m)
  try {
    localStorage.setItem(MODE_KEY, m)
  } catch {
    // Storage blocked: the choice still applies until the tab is closed.
  }
  window.dispatchEvent(new Event('aria-mode'))
}

// Auto mode tracks the OS live.
dark.addEventListener('change', () => getModeSetting() === 'auto' && setModeSetting('auto'))

/** The saved setting (light | night | auto) plus its setter; re-renders on any mode change, including OS flips in auto. */
export function useModeSetting(): [ModeSetting, (m: ModeSetting) => void] {
  const [, tick] = useReducer((n: number) => n + 1, 0)
  useEffect(() => {
    window.addEventListener('aria-mode', tick)
    return () => window.removeEventListener('aria-mode', tick)
  }, [])
  return [getModeSetting(), setModeSetting]
}
