import { User, Sparkles } from 'lucide-react'
import type { HistoryTurn } from '../../types'
import { ResponseCard } from './ResponseCard'
import { ResearchReport } from './ResearchReport'
import { ShapExplainer } from './ShapExplainer'
import { QuizWidget } from './QuizWidget'
import { api } from '../../api'
import { IntelligenceSummary } from './IntelligenceSummary'
import './MessageBubble.css'

const DOMAIN_LABEL: Record<string, string> = {
  finance: 'Personal finance', tutor: 'Tutor', market: 'Market analysis', equity_research: 'Equity research', company_intelligence: 'Company intelligence',
}

const SUGGESTIONS: Record<string, string[]> = {
  finance: ['What is my financial health score?', 'Can I start a SIP of ₹10,000?', 'What if I cut my expenses by ₹5,000 a month?'],
  tutor: ['Quiz me on this', 'Explain it with an example'],
  market: ['Which sectors are leading?', 'What does this mean for my investments?'],
  equity_research: ['Show the bear case', 'How does it compare with its peers?'],
  company_intelligence: ['Show the bear case', 'How does it compare with its peers?'],
}

export function MessageBubble({
  turn,
  sessionId,
  onQuizAnswered,
  onRetry,
  onOpenProfile,
  onAsk,
  isLast,
}: {
  turn: HistoryTurn
  sessionId: string
  onQuizAnswered: (correct: boolean) => void
  onRetry?: (query: string, correct?: boolean) => void
  onOpenProfile?: () => void
  onAsk?: (query: string) => void
  isLast?: boolean
}) {
  const { response } = turn
  const company = typeof response.company === 'string' ? response.company : (response.company as { name?: string } | undefined)?.name
  const badge = [DOMAIN_LABEL[response.domain] ?? response.domain.replace(/_/g, ' '), company].filter(Boolean).join(' · ')
  const failed = String(response.response ?? '').startsWith('Error:')
  const suggestions = isLast && onAsk && !failed && !response.missing_field ? SUGGESTIONS[response.domain] ?? [] : []
  const eng = response.engine as { assumptions?: unknown; numbers?: { rate_pct?: number } } | undefined
  const assumptions = typeof eng?.assumptions === 'string' ? `Assumptions: ${eng.assumptions}` : eng?.numbers?.rate_pct != null ? `Assumed return: ${eng.numbers.rate_pct}%` : undefined
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
          {failed && onRetry && (
            <button type="button" className="bubble-retry" onClick={() => onRetry(turn.query)}>Try again</button>
          )}
          {response.domain === 'company_intelligence' && <IntelligenceSummary data={response} />}
          {response.profile_basis && <p className="bubble-caption">{response.profile_basis}</p>}
          {response.data_basis && <p className="bubble-caption">{response.data_basis}</p>}
          {(response.profile_basis || response.domain === 'company_intelligence') && (
            <p className="bubble-caption" title={assumptions}>
              Figures calculated from your profile · wording by AI · not financial advice{assumptions && ' ⓘ'}
            </p>
          )}
          {response.ui_action === 'open_profile' && onOpenProfile && (
            <button type="button" className="bubble-retry" onClick={onOpenProfile}>{response.missing_field === 'transactions' ? 'Upload a statement' : 'Fill quick form'}</button>
          )}
          {typeof response.corrected_query === 'string' && onRetry && (
            <p className="bubble-caption">
              Showing results for {response.corrected_query} ·{' '}
              <button type="button" className="bubble-retry" onClick={() => onRetry(turn.query, false)}>use original</button>
            </p>
          )}
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

          {suggestions.length > 0 && (
            <div className="bubble-suggestions">
              {suggestions.map((s) => (
                <button key={s} type="button" className="bubble-retry" onClick={() => onAsk?.(s)}>{s}</button>
              ))}
            </div>
          )}

          {turn.audio_token && (
            <audio controls src={api.audioUrl(turn.audio_token)} className="bubble-audio" onError={(e) => { e.currentTarget.style.display = 'none' }} onLoadedMetadata={(e) => { if (!e.currentTarget.duration) e.currentTarget.style.display = 'none' }} />
          )}
        </div>
      </div>
    </div>
  )
}
