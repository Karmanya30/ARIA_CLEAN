import type { ChatMode, ChatResponse, InstrumentRange, FinanceProfile, ForYouData, ProfileState, ProfileSummary, ProgressState, ReportMeta, StatementImportResult, SpendingInsightsData, StatementPreview, Transaction, ValidationLatest } from './types'

import { accountOwner } from '../../authState'
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
const TONE_KEY = 'aria_adapt_tone'

/** Settings > Conversation: adapt ARIA's tone to how the user seems to feel (on unless switched off on this device). */
export function adaptTone(): boolean {
  try {
    return localStorage.getItem(TONE_KEY) !== 'off'
  } catch {
    return true
  }
}
export function setAdaptTone(on: boolean) {
  try {
    localStorage.setItem(TONE_KEY, on ? 'on' : 'off')
  } catch {
    /* storage blocked: the choice lasts until reload */
  }
}

/** Device-level id that owns saved research reports. The chat session id resets per browser tab, so
 * reports use the signed-in account when enabled, otherwise this private device capability. */
let memoryOwner: string | null = null
export function ownerId(): string {
  if (accountOwner()) return accountOwner()!
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
  news: { title: string; source: string; date: string; direction: string | null; net: number | null }[]
  call: { available: boolean; period?: string; net?: number | null; themes?: Record<string, { text: string; label: string | null; net: number | null }[]> }
  response: string
  for_you?: ForYouData | null
}

export interface SentimentResult {
  engine: 'finbert' | 'keywords'
  net: number
  label: string
  items: { text: string; label: string; net: number }[]
}

/** Paths for the GET instrument endpoints. They are plain strings so components can feed them to useMarket (cache + refresh). */
const ix = (id: string) => `/api/instruments/${encodeURIComponent(id)}`
export const instrumentPaths = {
  search: (q: string, type = '', limit = 12) =>
    `/api/instruments/search?q=${encodeURIComponent(q)}${type ? `&type=${type}` : ''}&limit=${limit}`,
  browse: (p: { type?: string; q?: string; sort?: string; page?: number; pageSize?: number }) =>
    `/api/instruments/browse?type=${p.type ?? ''}&q=${encodeURIComponent(p.q ?? '')}&sort=${p.sort ?? ''}&page=${p.page ?? 1}&page_size=${p.pageSize ?? 20}`,
  quote: (id: string) => `${ix(id)}/quote`,
  chart: (id: string, range: InstrumentRange) => `${ix(id)}/chart?range=${range}`,
  profile: (id: string) => `${ix(id)}/profile`,
  sip: (id: string, monthly: number, years: number) => `${ix(id)}/sip?monthly=${monthly}&years=${years}`,
}

export const api = {
  /** Ask ARIA about one instrument; the answer has the same shape as a chat reply. `history` is the earlier turns of this drawer conversation. */
  askInstrument: (id: string, question: string, sessionId: string, history: { role: 'user' | 'assistant'; content: string }[]) =>
    j<ChatResponse>('/api/instruments/ask', {
      method: 'POST',
      body: JSON.stringify({ id, question, session_id: sessionId, owner_id: ownerId(), history }),
    }),

  sendMessage: (query: string, sessionId: string, mode: ChatMode, correct = true) =>
    j<ChatResponse>('/api/chat', {
      method: 'POST',
      body: JSON.stringify({ query, request_id: crypto.randomUUID(), session_id: sessionId, mode, owner_id: ownerId(), adapt_tone: adaptTone(), correct }),
    }),

  getHistory: (sessionId: string) =>
    j<{ history: Array<{ query: string; response: ChatResponse; audio_path?: string }> }>(
      `/api/chat/history?session_id=${encodeURIComponent(sessionId)}&owner_id=${encodeURIComponent(ownerId())}`,
    ),

  clearChat: (sessionId: string) =>
    j<{ status: string }>('/api/chat/clear', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, owner_id: ownerId() }),
    }),

  // multipart: the browser sets the Content-Type (with boundary) itself
  parseStatement: async (file: File): Promise<StatementPreview> => {
    const form = new FormData()
    form.append('file', file)
    form.append('session_id', ownerId())
    const res = await fetch('/api/transactions/parse', { method: 'POST', body: form })
    if (!res.ok) throw new Error(await extractErrorDetail(res))
    return res.json()
  },

  importStatement: (importId: string, applyToProfile: boolean) =>
    j<StatementImportResult>('/api/transactions/import', {
      method: 'POST',
      body: JSON.stringify({ session_id: ownerId(), import_id: importId, apply_to_profile: applyToProfile }),
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

  // Profile + transactions are keyed by the device owner id (sessionStorage session ids are lost on tab close).
  getProfile: () => j<ProfileState>(`/api/profile?session_id=${encodeURIComponent(ownerId())}`),

  getProfileSummary: () => j<ProfileSummary>(`/api/profile/summary?session_id=${encodeURIComponent(ownerId())}`),

  /** Partial update; a null value deletes that fact. */
  saveProfile: (fields: { [K in keyof FinanceProfile]?: FinanceProfile[K] | null }) =>
    j<ProfileState>('/api/profile', { method: 'POST', body: JSON.stringify({ session_id: ownerId(), ...fields }) }),

  forgetStyle: () => j<{ deleted: boolean }>(`/api/profile/style?session_id=${encodeURIComponent(ownerId())}`, { method: 'DELETE' }),
  deleteProfile: () => j<{ deleted: boolean }>(`/api/profile?session_id=${encodeURIComponent(ownerId())}`, { method: 'DELETE' }),

  getInsights: () => j<SpendingInsightsData>(`/api/transactions/insights?session_id=${encodeURIComponent(ownerId())}`),

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
      body: JSON.stringify({ session_id: sessionId, owner_id: ownerId() }),
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

  validationLatest: (symbol: string) => j<ValidationLatest>(`/api/research/validation/latest?symbol=${encodeURIComponent(symbol)}`),

  validationStart: (symbol: string, force = false) =>
    j<{ run_id: string; status: ValidationLatest['status'] }>('/api/research/validation', { method: 'POST', body: JSON.stringify({ symbol, force }) }),

  companyIntel: (q: string) => j<CompanyIntel>(`/api/research/intelligence?q=${encodeURIComponent(q)}&owner_id=${encodeURIComponent(ownerId())}`),

  sentiment: (texts: string[]) =>
    j<SentimentResult>('/api/research/sentiment', { method: 'POST', body: JSON.stringify({ texts }) }),

  startTavus: (sessionId: string) =>
    j<{ conversation_id: string; conversation_url: string; embed_url: string }>('/api/tavus/start', {
      method: 'POST',
      body: JSON.stringify({ session_id: sessionId, owner_id: ownerId() }),
    }),

  // Pass the id you started: a bare end would stop whichever call is active now, possibly a newer one.
  endTavus: (conversationId?: string) =>
    j<{ status: string }>('/api/tavus/end', { method: 'POST', body: JSON.stringify({ conversation_id: conversationId ?? null }) }),
}
