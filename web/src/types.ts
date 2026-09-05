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

// Stage 13 -- typed structured-output contract, mirroring shared/blocks.py.
// Replaces web/src/components/chat/ResponseCard.tsx's regex parsing of
// "Insight:"/"Analysis:"/etc labels out of raw text, which force-fit every
// response into the same four boxes regardless of shape. `blocks` is the
// new contract; `response` (the plain string) is still always present too
// -- not a flag-day break, see BlockRenderer.tsx's fallback.
export interface TextBlock {
  type: 'text'
  content: string
}
export interface MetricBlock {
  type: 'metric'
  label: string
  value: string
  unit?: string | null
}
export interface FormulaBlock {
  type: 'formula'
  expression: string
  variables: string[]
}
export interface TableBlock {
  type: 'table'
  columns: string[]
  rows: string[][]
}
export interface BreakdownBlock {
  type: 'breakdown'
  categories: string[]
  amounts: number[]
  percentages?: number[] | null
}
export interface ChartBlock {
  type: 'chart'
  chart_type: 'line' | 'bar' | 'donut'
  labels: string[]
  data: number[]
  series_name?: string | null
  lower_band?: number[] | null
  upper_band?: number[] | null
}
export interface RiskFactor {
  name: string
  contribution: number
}
export interface RiskBlock {
  type: 'risk'
  score: number
  level: string
  factors: RiskFactor[]
}
export interface RecommendationBlock {
  type: 'recommendation'
  title: string
  rationale: string
  actions: string[]
}
export interface ComparisonRow {
  name: string
  metrics: Record<string, string>
}
export interface ComparisonBlock {
  type: 'comparison'
  title: string
  rows: ComparisonRow[]
}
export interface AlertBlock {
  type: 'alert'
  severity: 'info' | 'warning' | 'error'
  message: string
}
export interface ExplanationBlock {
  type: 'explanation'
  label: string
  content: string
}
export interface DefinitionBlock {
  type: 'definition'
  term: string
  definition: string
}
export interface MCQBlockData {
  type: 'mcq'
  question: string
  correct_answer: string
  wrong_answers: string[]
  explanation: string
  concept_id: string
}
export interface HintBlock {
  type: 'hint'
  level: number
  content: string
}
export interface MasteryBlock {
  type: 'mastery'
  topic: string
  concept_id: string
  score: number
}

export type Block =
  | TextBlock
  | MetricBlock
  | FormulaBlock
  | TableBlock
  | BreakdownBlock
  | ChartBlock
  | RiskBlock
  | RecommendationBlock
  | ComparisonBlock
  | AlertBlock
  | ExplanationBlock
  | DefinitionBlock
  | MCQBlockData
  | HintBlock
  | MasteryBlock

export interface ChatResponse {
  domain: string
  query: string
  response: string
  blocks?: Block[]
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
