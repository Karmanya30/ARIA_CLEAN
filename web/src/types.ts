export type ChatMode = 'Normal Mode' | 'Conversational Mode' | 'Tavus CVI Mode (WebRTC)'

export interface RiskInfo {
  label: string
  confidence: number
  top_features: [string, number][]
}

export interface QuizItem {
  question: string
  correct_answer: string
  wrong_answers: string[]
  explanation: string
  concept_id: string
}

export interface ChatResponse {
  domain: string
  query: string
  response: string
  company?: string
  risk?: RiskInfo
  quiz?: QuizItem
  concept_name?: string
  audio_token?: string | null
  [key: string]: unknown
}

export interface HistoryTurn {
  query: string
  response: ChatResponse
  audio_token?: string | null
  quiz_answered?: boolean
  quiz_correct?: boolean
}

export interface FinancialProfile {
  user_id: string
  monthly_income: number
  age: number
  dependents: number
  existing_emi: number
  emergency_fund_months: number
  city_tier: number
  tax_regime: string
  risk_label: string | null
  risk_confidence: number | null
  risk_top_features: [string, number][]
}

export interface Transaction {
  id: number
  date: string
  category: string
  amount: number
  merchant: string | null
  channel: string | null
}

export interface ProgressItem {
  concept_id: string
  name: string
  mastery: number
}

export interface ProgressState {
  engaged: ProgressItem[]
  total_interactions: number
}
