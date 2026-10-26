import { useEffect, useState } from 'react'

const STAGES: [number, string][] = [
  [0, 'Reading your question…'],
  [4, 'Checking your profile and live data…'],
  [10, 'Working out the numbers…'],
  [25, 'Still working: reports can take up to a minute'],
]

export function ThinkingStatus() {
  const [secs, setSecs] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setSecs((s) => s + 1), 1000)
    return () => clearInterval(t)
  }, [])
  const text = [...STAGES].reverse().find(([s]) => secs >= s)![1]
  return (
    <p className="chat-status" role="status">
      <span className="thinking-dot" aria-hidden="true" /> {text}
    </p>
  )
}
