export type ThemeId = 'classic' | 'vitara'

export const THEMES: { id: ThemeId; label: string; blurb: string }[] = [
  { id: 'classic', label: 'Classic', blurb: 'The original ARIA look: left sidebar, cool blue accent, compact cards.' },
  {
    id: 'vitara',
    label: 'Vitara',
    blurb: 'Warm ivory canvas, top navigation bar, rounded pill controls and a deep green accent.',
  },
]

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
