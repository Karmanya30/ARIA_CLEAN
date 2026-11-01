import { useState } from 'react'

const KEY = 'aria_session_id'

function readId(): string | null {
  try { const id = localStorage.getItem(KEY); if (id) return id } catch { /* storage blocked */ }
  try { return sessionStorage.getItem(KEY) } catch { return null }
}

function remember(id: string) {
  try { localStorage.setItem(KEY, id) } catch { /* retain in component state */ }
  try { sessionStorage.setItem(KEY, id) } catch { /* retain in component state */ }
}

/** Resume the active conversation across browser restarts; reset starts a new one, select opens an earlier one.
 * `restored` is false when this browser had no saved conversation (first visit, a new device, or just signed in), so the
 * app can open the most recent saved one from the server instead of a blank chat. */
export function useSessionId(): [string, () => void, (id: string) => void, boolean] {
  const [restored] = useState(() => !!readId())
  const [id, setId] = useState(() => {
    const saved = readId() || crypto.randomUUID()
    remember(saved)
    return saved
  })

  function select(next: string) {
    remember(next)
    setId(next)
  }

  return [id, () => select(crypto.randomUUID()), select, restored]
}
