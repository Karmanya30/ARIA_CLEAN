import { User, Sparkles } from 'lucide-react'
import type { HistoryTurn } from '../../types'
import { ResponseCard } from './ResponseCard'
import { BlockList } from './BlockRenderer'
import { ShapExplainer } from './ShapExplainer'
import { QuizWidget } from './QuizWidget'
import { api } from '../../api'
import './MessageBubble.css'

export function MessageBubble({
  turn,
  sessionId,
  onQuizAnswered,
}: {
  turn: HistoryTurn
  sessionId: string
  onQuizAnswered: (correct: boolean) => void
}) {
  const { response } = turn
  const badge = `Domain: ${response.domain}${response.company ? ` · Company: ${response.company}` : ''}`
  // Stage 13: every pipeline now emits `blocks`, but this stays a real
  // fallback (not a flag-day break) for any response shape that doesn't
  // -- e.g. an older cached session turn from before this shipped.
  const hasBlocks = Array.isArray(response.blocks) && response.blocks.length > 0

  return (
    <div className="message-pair">
      <div className="bubble bubble-user">
        <span className="bubble-avatar">
          <User size={15} />
        </span>
        <p>{turn.query}</p>
      </div>

      <div className="bubble bubble-assistant">
        <span className="bubble-avatar bubble-avatar-assistant">
          <Sparkles size={15} />
        </span>
        <div className="bubble-content">
          {hasBlocks ? (
            <BlockList
              blocks={response.blocks!}
              sessionId={sessionId}
              seed={`${sessionId}-${turn.query}`}
              quizAnswered={turn.quiz_answered}
              quizCorrect={turn.quiz_correct}
              onQuizAnswered={onQuizAnswered}
            />
          ) : (
            <>
              <ResponseCard text={response.response} />
              {response.risk?.top_features?.length ? (
                <ShapExplainer label={response.risk.label} topFeatures={response.risk.top_features} />
              ) : null}
              {response.quiz && !turn.quiz_answered && (
                <QuizWidget
                  quiz={response.quiz}
                  sessionId={sessionId}
                  seed={`${sessionId}-${turn.query}`}
                  onAnswered={onQuizAnswered}
                />
              )}
              {response.quiz && turn.quiz_answered && (
                <div className={turn.quiz_correct ? 'quiz-result quiz-correct' : 'quiz-result quiz-incorrect'}>
                  {turn.quiz_correct ? `Correct! ${response.quiz.explanation}` : `Not quite. ${response.quiz.explanation}`}
                </div>
              )}
            </>
          )}

          <p className="bubble-caption">{badge}</p>

          {turn.audio_token && (
            <audio controls src={api.audioUrl(turn.audio_token)} className="bubble-audio" />
          )}
        </div>
      </div>
    </div>
  )
}
