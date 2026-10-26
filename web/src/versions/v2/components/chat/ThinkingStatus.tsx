import { useEffect, useState } from 'react'
import './ThinkingStatus.css'

const STAGES: [number, string][] = [
  [0, 'Reading your question'],
  [4, 'Checking your profile and live data'],
  [10, 'Working out the numbers'],
  [25, 'Still working — reports can take a minute'],
]

export function ThinkingStatus() {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const text = [...STAGES].reverse().find(([s]) => secs >= s)![1]
  return (
    <div className="thinking-status" role="status" aria-live="polite">
      <div className="thinking-bubble">
        <div className="thinking-dots-row">
          <span className="td" style={{ animationDelay: '0ms' }} aria-hidden="true" />
          <span className="td" style={{ animationDelay: '160ms' }} aria-hidden="true" />
          <span className="td" style={{ animationDelay: '320ms' }} aria-hidden="true" />
        </div>
        <span className="thinking-label">{text}</span>
      </div>
    </div>
  )
}
