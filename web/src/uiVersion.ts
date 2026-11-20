/** Which app interface to load: "Classic" (versions/v2), "Aurora" (versions/v3) or "Pulse" (versions/v4).
 * Saved per browser; ?ui=pulse, ?ui=aurora or ?ui=classic in the URL switches it (handy for demo links). */
export type UiId = 'classic' | 'aurora' | 'pulse'
export const UIS: { id: UiId; label: string; blurb: string }[] = [
  { id: 'classic', label: 'Classic', blurb: 'The current ARIA layout with the top navigation bar.' },
  { id: 'aurora', label: 'Aurora', blurb: 'Side navigation, glass panels and aurora lighting.' },
  { id: 'pulse', label: 'Pulse (new)', blurb: 'Top navigation with a live market ribbon, mood gauge and flashing prices.' },
]
const KEY = 'aria_ui'

export function getUi(): UiId {
  try {
    const q = new URLSearchParams(window.location.search).get('ui')
    if (UIS.some((u) => u.id === q)) localStorage.setItem(KEY, q!)
    return UIS.find((u) => u.id === localStorage.getItem(KEY))?.id ?? 'classic'
  } catch {
    return 'classic'
  }
}

/** Saves the choice and reloads, so only one interface's styles are ever on the page. */
export function setUi(id: UiId) {
  try {
    localStorage.setItem(KEY, id)
  } catch {
    // Storage blocked: nothing to remember, the reload keeps the current interface.
  }
  const url = new URL(window.location.href)
  url.searchParams.delete('ui') // a stale ?ui= would override the new choice
  window.history.replaceState(window.history.state, '', url.toString())
  window.location.reload() // replace() to the same URL + #hash is a same-page jump, not a reload
}
