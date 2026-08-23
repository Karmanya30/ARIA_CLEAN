import type { ChatMode, ChatResponse, FinancialProfile, ProgressState, Transaction } from './types'

const BASE = ''

// FastAPI's HTTPException serializes as {"detail": "message"}. Surfacing
// the raw response body (as the old `res.text()` calls did) showed users
// a literal JSON blob -- e.g. `{"detail":"Could not transcribe the
// audio."}` -- instead of the human-readable message inside it.
async function extractErrorDetail(res: Response): Promise<string> {
  const raw = await res.text().catch(() => res.statusText)
  try {
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed.detail === 'string') return parsed.detail
  } catch {
    // not JSON -- fall through and use the raw text
  }
  return raw || res.statusText
}

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  })
  if (!res.ok) {
    throw new Error(await extractErrorDetail(res))
  }
  return res.json() as Promise<T>
}

export const api = {
  sendMessage: (query: string, sessionId: string, mode: ChatMode) =>
    j<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ query, session_id: sessionId, mode }),
    }),

  getHistory: (sessionId: string) =>
    j<{ history: Array<{ query: string; response: ChatResponse; audio_path?: string }> }>(
      `/api/chat/history?session_id=${encodeURIComponent(sessionId)}`,
    ),

  clearChat: (sessionId: string) =>
    j<{ status: string }>('/api/chat/clear', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    }),

  transcribe: async (blob: Blob): Promise<{ text: string }> => {
    const form = new FormData()
    form.append('file', blob, 'recording.webm')
    const res = await fetch('/api/voice/transcribe', { method: 'POST', body: form })
    if (!res.ok) throw new Error(await extractErrorDetail(res))
    return res.json()
  },

  audioUrl: (token: string) => `/api/audio/${token}`,
  avatarUrl: (token?: string | null) => `/avatar/render${token ? `?audio_token=${token}` : ''}`,

  getProfile: (sessionId: string) =>
    j<FinancialProfile | null>(`/api/profile?session_id=${encodeURIComponent(sessionId)}`),

  saveProfile: (sessionId: string, fields: Partial<FinancialProfile>) =>
    j<{ status: string }>('/api/profile', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, ...fields }),
    }),

  getTransactions: (sessionId: string) =>
    j<Transaction[]>(`/api/transactions?session_id=${encodeURIComponent(sessionId)}`),

  addTransaction: (sessionId: string, tx: Omit<Transaction, 'id'>) =>
    j<{ status: string }>('/api/transactions', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, ...tx }),
    }),

  clearTransactions: (sessionId: string) =>
    j<{ status: string }>(`/api/transactions?session_id=${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    }),

  loadSampleTransactions: (sessionId: string) =>
    j<{ status: string; count: string }>('/api/transactions/sample', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    }),

  getProgress: (sessionId: string) =>
    j<ProgressState>(`/api/progress?session_id=${encodeURIComponent(sessionId)}`),

  answerQuiz: (sessionId: string, conceptId: string, isCorrect: boolean) =>
    j<{ mastery: Record<string, number> }>('/api/quiz/answer', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, concept_id: conceptId, is_correct: isCorrect }),
    }),

  startTavus: (sessionId: string) =>
    j<{ conversation_url: string; embed_url: string }>('/api/tavus/start', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    }),

  endTavus: () => j<{ status: string }>('/api/tavus/end', { method: 'POST' }),
}
