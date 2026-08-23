import { useMemo, useState } from 'react'
import type { QuizItem } from '../../types'
import { api } from '../../api'
import './QuizWidget.css'

/** Renders and grades the quiz the DQN teaching policy generates whenever
 * it picks "ask_quiz" -- this is what actually closes the loop into
 * modules.tutor.orchestrator.record_answer(), which is the only thing
 * that ever moves DKT mastery off its cold-start default. */
export function QuizWidget({
  quiz,
  sessionId,
  seed,
  onAnswered,
}: {
  quiz: QuizItem
  sessionId: string
  seed: string
  onAnswered: (correct: boolean) => void
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const [answered, setAnswered] = useState(false)
  const [correct, setCorrect] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const options = useMemo(() => {
    const all = [...quiz.wrong_answers, quiz.correct_answer]
    // Deterministic per-turn shuffle so it doesn't reorder on re-render.
    let seedNum = 0
    for (let i = 0; i < seed.length; i++) seedNum = (seedNum * 31 + seed.charCodeAt(i)) >>> 0
    const rand = () => {
      seedNum = (seedNum * 1103515245 + 12345) >>> 0
      return seedNum / 0xffffffff
    }
    const arr = [...all]
    for (let i = arr.length - 1; i > 0; i--) {
      const j = Math.floor(rand() * (i + 1))
      ;[arr[i], arr[j]] = [arr[j], arr[i]]
    }
    return arr
  }, [quiz, seed])

  async function submit() {
    if (!selected || submitting) return
    setSubmitting(true)
    const isCorrect = selected.trim().toLowerCase() === quiz.correct_answer.trim().toLowerCase()
    try {
      await api.answerQuiz(sessionId, quiz.concept_id, isCorrect)
      setCorrect(isCorrect)
      setAnswered(true)
      onAnswered(isCorrect)
    } finally {
      setSubmitting(false)
    }
  }

  if (answered) {
    return (
      <div className={correct ? 'quiz-result quiz-correct' : 'quiz-result quiz-incorrect'}>
        {correct ? (
          <p>Correct! {quiz.explanation}</p>
        ) : (
          <p>
            Not quite — correct answer: <strong>{quiz.correct_answer}</strong>. {quiz.explanation}
          </p>
        )}
      </div>
    )
  }

  return (
    <div className="quiz-widget">
      <p className="quiz-question">Quick check: {quiz.question}</p>
      <div className="quiz-options">
        {options.map((opt) => (
          <label key={opt} className={selected === opt ? 'quiz-option selected' : 'quiz-option'}>
            <input
              type="radio"
              name={`quiz-${seed}`}
              checked={selected === opt}
              onChange={() => setSelected(opt)}
            />
            {opt}
          </label>
        ))}
      </div>
      <button className="btn btn-primary" onClick={submit} disabled={!selected || submitting}>
        Submit answer
      </button>
    </div>
  )
}
