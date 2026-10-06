import { User, Sparkles } from 'lucide-react'
import type { HistoryTurn } from '../../types'
import { ResponseCard } from './ResponseCard'
import { ResearchReport } from './ResearchReport'
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
  const headlines = response.context?.news_headlines ?? []

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
          <ResponseCard text={response.response} />
          <p className="bubble-caption">{badge}</p>
          {headlines.length > 0 && (
            <details className="bubble-news">
              <summary>Based on {headlines.length} live headlines</summary>
              <ul>
                {headlines.map((h) => (
                  <li key={h}>{h}</li>
                ))}
              </ul>
            </details>
          )}

          {response.report && <ResearchReport report={response.report} reportId={response.report_id} />}
          {response.fund_report && response.report_id && (
            <p className="bubble-caption">
              <a href={api.reportHtmlUrl(response.report_id)} target="_blank" rel="noreferrer">Open the full fund report</a> ·{' '}
              <a href={api.reportDownloadUrl(response.report_id, 'pdf')}>PDF</a> · <a href={api.reportDownloadUrl(response.report_id, 'html')}>HTML</a>
            </p>
          )}

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

          {turn.audio_token && (
            <audio controls src={api.audioUrl(turn.audio_token)} className="bubble-audio" />
          )}
        </div>
      </div>
    </div>
  )
}
