import type { useTavusSession } from '../../hooks/useTavusSession'
import { ResponseCard } from './ResponseCard'
import './TavusTranscript.css'

/** Main-column half of Tavus CVI Mode -- the live transcript. See
 * TavusVideo for the other half (sidebar). */
export function TavusTranscript({ session }: { session: ReturnType<typeof useTavusSession> }) {
  const { embedUrl, transcript } = session

  if (!embedUrl) return null

  return (
    <div className="tavus-transcript-panel">
      <div className="mono-label">Live transcript</div>
      <div className="tavus-transcript">
        {transcript.length === 0 && (
          <p className="tavus-transcript-empty">Your conversation will appear here once you start speaking.</p>
        )}
        {transcript.map((turn, i) => (
          <div key={i} className="tavus-turn">
            <div className="tavus-turn-user">{turn.query}</div>
            <ResponseCard text={turn.response.response} />
          </div>
        ))}
      </div>
    </div>
  )
}
