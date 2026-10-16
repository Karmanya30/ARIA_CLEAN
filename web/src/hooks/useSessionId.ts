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

/** Resume the active conversation across browser restarts; reset starts a new one. */
export function useSessionId(): [string, () => void] {
  const [id, setId] = useState(() => {
    const saved = readId() || crypto.randomUUID()
    remember(saved)
    return saved
  })

  function reset() {
    const fresh = crypto.randomUUID()
    remember(fresh)
    setId(fresh)
  }

  return [id, reset]
}
