import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { HistoryTurn } from '../types'

/** Paid Tavus CVI mode: a real WebRTC video call with the avatar, embedded
 * via api/routes/avatar.py's /embed route (a custom daily-js call UI --
 * see interface/avatar/tavus_embed.html -- not Tavus/Daily's default
 * prebuilt call room). The conversation's turns land in the same
 * core.session history /api/chat/history serves for text chat (Tavus's
 * callback and this frontend's own chat calls run in the same API process
 * now), so this polls that endpoint for a live transcript underneath.
 *
 * Session state lives in this hook (not a single mounted/unmounted
 * component) so the video call and its transcript can render in separate
 * parts of the page -- video/controls in the sidebar, transcript in the
 * main chat column -- while driving one shared connection. `enabled` gates
 * the start/end instead of mount/unmount, since ChatTab itself never
 * unmounts when the mode dropdown changes. `attempt` is what actually
 * forces a new call to start -- bumping plain state (error/embedUrl) does
 * NOT re-run the effect below, since neither is in its dependency array;
 * restart() has to change something that IS. */
export function useTavusSession(sessionId: string, enabled: boolean) {
  const [embedUrl, setEmbedUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [transcript, setTranscript] = useState<HistoryTurn[]>([])
  const [ended, setEnded] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const startedRef = useRef(false)

  useEffect(() => {
    if (!enabled) {
      // Leaving Tavus mode (or never entered it) -- make sure a later
      // re-entry starts a fresh conversation rather than a stale one.
      startedRef.current = false
      setEmbedUrl(null)
      setError(null)
      setTranscript([])
      setEnded(false)
      return
    }
    if (startedRef.current) return
    startedRef.current = true

    setLoading(true)
    setEnded(false)
    setError(null)
    api
      .startTavus(sessionId)
      .then((res) => setEmbedUrl(res.embed_url))
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to start Tavus.'))
      .finally(() => setLoading(false))

    // Runs when `enabled` flips back to false, `attempt` bumps (a
    // restart), sessionId changes, or ChatTab unmounts -- always ends
    // the paid conversation before any new one starts.
    return () => {
      api.endTavus().catch(() => {})
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, sessionId, attempt])

  useEffect(() => {
    if (!embedUrl) return
    const poll = setInterval(() => {
      api
        .getHistory(sessionId)
        .then((res) => setTranscript(res.history as HistoryTurn[]))
        .catch(() => {})
    }, 2000)
    return () => clearInterval(poll)
  }, [embedUrl, sessionId])

  // The embed iframe (interface/avatar/tavus_embed.html) posts this when
  // the call ends -- either the user clicked "End call" or it dropped on
  // its own (replica left, network blip, Tavus's own timeout). Without
  // this, the React side never found out the call was over and kept
  // showing the dead iframe with no way to start a new one short of
  // switching the mode dropdown away and back.
  useEffect(() => {
    function onMessage(ev: MessageEvent) {
      if (ev.data && ev.data.type === 'aria_tavus_call_ended') {
        setEnded(true)
      }
    }
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])

  function restart() {
    startedRef.current = false
    setEmbedUrl(null)
    setError(null)
    setEnded(false)
    setAttempt((a) => a + 1)
  }

  return { embedUrl, error, loading, transcript, ended, restart }
}
