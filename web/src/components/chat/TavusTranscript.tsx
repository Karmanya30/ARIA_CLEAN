import { useState } from 'react'
import type { useTavusSession } from '../../hooks/useTavusSession'
import { ResponseCard } from './ResponseCard'
import { BlockList } from './BlockRenderer'
import './TavusTranscript.css'

/** Main-column half of Tavus CVI Mode -- the live transcript. See
 * TavusVideo for the other half (sidebar). */
export function TavusTranscript({
  session,
  sessionId,
}: {
  session: ReturnType<typeof useTavusSession>
  sessionId: string
}) {
  const { embedUrl, transcript } = session
  // Quiz-answered state isn't part of the polled history turn (the backend
  // doesn't track it), so it's tracked locally by index the same way
  // ChatTab.tsx does for the text/voice thread.
  const [quizState, setQuizState] = useState<Record<number, boolean>>({})

  if (!embedUrl) return null

  return (
    <div className="tavus-transcript-panel">
      <div className="mono-label">Live transcript</div>
      <div className="tavus-transcript">
        {transcript.length === 0 && (
          <p className="tavus-transcript-empty">Your conversation will appear here once you start speaking.</p>
        )}
        {transcript.map((turn, i) => {
          const { response } = turn
          // Stage 13: mirrors MessageBubble.tsx's block-vs-plain-text
          // fallback, which this panel had fallen out of sync with.
          const hasBlocks = Array.isArray(response.blocks) && response.blocks.length > 0
          return (
            <div key={i} className="tavus-turn">
              <div className="tavus-turn-user">{turn.query}</div>
              {hasBlocks ? (
                <BlockList
                  blocks={response.blocks!}
                  sessionId={sessionId}
                  seed={`tavus-${i}-${turn.query}`}
                  quizAnswered={quizState[i] ?? false}
                  quizCorrect={quizState[i]}
                  onQuizAnswered={(correct) => setQuizState((s) => ({ ...s, [i]: correct }))}
                />
              ) : (
                <ResponseCard text={response.response} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
