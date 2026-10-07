import type { ChatMode, ChatResponse, FinancialProfile, ProgressState, ReportMeta, Transaction } from './types'

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

const OWNER_KEY = 'aria_owner_id'

/** Device-level id that owns saved research reports. The chat session id resets per browser tab, so
 * reports are keyed by this instead (ARIA has no accounts). Falls back to a per-page id if storage is blocked. */
let memoryOwner: string | null = null
export function ownerId(): string {
  try {
    const existing = localStorage.getItem(OWNER_KEY)
    if (existing) return existing
    const fresh = crypto.randomUUID()
    localStorage.setItem(OWNER_KEY, fresh)
    return fresh
  } catch {
    return (memoryOwner ??= crypto.randomUUID())
  }
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

export interface CompanyIntel {
  domain: string
  company: { name: string; symbol: string }
  intelligence: {
    score: number
    band: string
    coverage: number
    low_evidence: boolean
    components: { name: string; weight: number; value: number }[]
    divergences: { id: string; severity: string; text: string; evidence: string }[]
  }
  scorecard: {
    pillars: { name: string; rating: string; points: number; reasons: { sign: string; text: string }[] }[]
    overlay: { tone: string; reading: string }
  }
  news: { title: string; source: string; date: string; direction: string; net: number }[]
  call: { available: boolean; period?: string; net?: number; themes?: string[] }
  response: string
}

export interface SentimentResult {
  engine: 'finbert' | 'keywords'
  net: number
  label: string
  items: { text: string; label: string; net: number }[]
}

export const api = {
  sendMessage: (query: string, sessionId: string, mode: ChatMode) =>
    j<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ query, session_id: sessionId, mode, owner_id: ownerId() }),
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

  listReports: () => j<ReportMeta[]>(`/api/research/reports?owner_id=${encodeURIComponent(ownerId())}`),

  reportHtmlUrl: (id: string, kind = '', print = false) =>
    `/api/research/reports/${id}/html?owner_id=${encodeURIComponent(ownerId())}${kind ? `&kind=${kind}` : ''}${print ? '&print=true' : ''}`,

  reportDownloadUrl: (id: string, format: 'html' | 'md' | 'json' | 'pdf', kind = '') =>
    `/api/research/reports/${id}/download?format=${format}&owner_id=${encodeURIComponent(ownerId())}${kind ? `&kind=${kind}` : ''}`,

  regenerateReport: (id: string) =>
    j<{ report_id: string; meta: ReportMeta }>(`/api/research/reports/${id}/regenerate`, {
      method: 'POST',
      body: JSON.stringify({ owner_id: ownerId() }),
    }),

  deleteReport: (id: string) =>
    j<{ status: string }>(`/api/research/reports/${id}?owner_id=${encodeURIComponent(ownerId())}`, { method: 'DELETE' }),

  companyIntel: (q: string) => j<CompanyIntel>(`/api/research/intelligence?q=${encodeURIComponent(q)}`),

  sentiment: (texts: string[]) =>
    j<SentimentResult>('/api/research/sentiment', { method: 'POST', body: JSON.stringify({ texts }) }),

  startTavus: (sessionId: string) =>
    j<{ conversation_id: string; conversation_url: string; embed_url: string }>('/api/tavus/start', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId }),
    }),

  // Pass the id you started: a bare end would stop whichever call is active now, possibly a newer one.
  endTavus: (conversationId?: string) =>
    j<{ status: string }>('/api/tavus/end', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId ?? null }) }),
}
