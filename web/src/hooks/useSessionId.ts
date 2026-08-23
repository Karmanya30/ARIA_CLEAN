import { useState } from 'react'

const KEY = 'aria_session_id'

function makeId(): string {
  return crypto.randomUUID()
}

/** One id per browser tab, matching the old Streamlit app's per-tab
 * uuid4() session (sessionStorage clears on tab close, persists across
 * reloads within the tab -- same effective lifetime). */
export function useSessionId(): [string, () => void] {
  const [id, setId] = useState(() => {
    const existing = sessionStorage.getItem(KEY)
    if (existing) return existing
    const fresh = makeId()
    sessionStorage.setItem(KEY, fresh)
    return fresh
  })

  function reset() {
    const fresh = makeId()
    sessionStorage.setItem(KEY, fresh)
    setId(fresh)
  }

  return [id, reset]
}
