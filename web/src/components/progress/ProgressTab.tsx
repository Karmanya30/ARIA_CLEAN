import { useEffect, useState } from 'react'
import { api } from '../../api'
import type { ProgressState } from '../../types'
import './ProgressTab.css'

export function ProgressTab({ sessionId }: { sessionId: string }) {
  const [state, setState] = useState<ProgressState | null>(null)

  useEffect(() => {
    api.getProgress(sessionId).then(setState)
  }, [sessionId])

  return (
    <div>
      <h2>Your Learning Progress</h2>
      <p className="tab-caption">Module 2's per-concept mastery, estimated by the DKT model from your quiz answers.</p>

      {!state || state.total_interactions === 0 ? (
        <div className="banner-info">Ask ARIA to explain a financial concept in the Chat tab to start building your progress here.</div>
      ) : state.engaged.length === 0 ? (
        <div className="banner-info">No mastery recorded yet — answer a quiz question to see progress here.</div>
      ) : (
        <>
          <div className="card progress-list">
            {state.engaged.map((item) => (
              <div key={item.concept_id} className="progress-item">
                <div className="progress-item-head">
                  <span>{item.name}</span>
                  <span className="progress-pct">{Math.round(item.mastery * 100)}%</span>
                </div>
                <div className="progress-bar">
                  <div className="progress-bar-fill" style={{ width: `${Math.min(100, item.mastery * 100)}%` }} />
                </div>
              </div>
            ))}
          </div>
          <p className="tab-caption">{state.total_interactions} total interactions recorded this session.</p>
        </>
      )}
    </div>
  )
}
