export type ChatMode = 'Normal Mode' | 'Conversational Mode' | 'Live Avatar (Free)' | 'Tavus CVI Mode (WebRTC)'

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

// ── Equity research report (modules/equity_research/intelligence/report.py) ──
export interface ReportFact {
  id: string
  label: string
  text: string
  period: string
  source: string
  kind: 'raw' | 'calculated' | 'assumption'
  method: string
}

export interface ReportTable {
  title: string
  columns: string[]
  rows: { label: string; unit: string; kind: string; values: Record<string, number | null> }[]
  source: string
}

export interface ValuationMethod {
  key: string
  label: string
  low: number
  mid: number
  high: number
  weight: number
  basis: string
}

export interface DebateArgument {
  claim: string
  evidence: { id: string; label: string; period: string; value: string }[]
}

export interface ResearchReportData {
  title: string
  status: 'publishable' | 'caveated'
  company: { name: string; symbol: string; sector: string | null; industry: string | null; price: number | null; market_cap_cr: number | null; as_of: string; basis: string }
  stance: {
    rating: 'BUY' | 'HOLD' | 'SELL' | null
    stance: string
    fair_value: number | null
    low: number | null
    high: number | null
    upside_pct: number | null
    confidence: string | null
    withheld: boolean
    price: number | null
    notes: string[]
  }
  for_you?: ForYouData | null
  thesis: string[]
  business: string
  financials: { text: string; tables: ReportTable[] }
  valuation: {
    text: string
    methods: ValuationMethod[]
    skipped: Record<string, string>
    notes: string[]
    comps: { group: string; peers: { symbol: string; name: string; pe: number | null; pb: number | null; ev_ebitda: number | null; excluded: string[] }[] } | null
    dcf: {
      inputs: { growth: number[]; wacc: number; terminal_growth: number }
      result: { tv_share: number }
      sensitivity: { wacc_values: number[]; tg_values: number[]; prices: (number | null)[][] } | null
      margin_swing: [number | null, number | null] | null
      reverse: { implied_growth: number | null; reason: string; ceiling_price: number | null } | null
    } | null
  }
  risks: { category: string; severity: string; title: string; detail: string; origin: 'rule' | 'llm' }[]
  catalysts: string[]
  news: { title: string; source: string; date: string }[]
  debate: {
    bull: DebateArgument[]
    bear: DebateArgument[]
    judge: { call: string; conviction: number; swing_factor: string; change_my_mind: string } | null
    aligned: boolean | null
  }
  assumptions: ReportFact[]
  audit: {
    status: string
    checks: { name: string; title: string; status: 'pass' | 'info' | 'review' | 'blocked'; findings: string[] }[]
  }
  sources: { source: string; count: number }[]
  disclaimer: string
  markdown: string
  meta?: ReportMeta
}

export interface ReportMeta {
  id: string
  kind: string
  symbol: string
  company: string
  version: number
  status: 'publishable' | 'caveated' | null
  rating: 'BUY' | 'HOLD' | 'SELL' | null
  stance: string | null
  fair_value: number | null
  price: number | null
  upside_pct: number | null
  confidence: string | null
  data_as_of: string | null
  created_at: string | null
}

export interface ForYouData { lines: string[]; basis: string; caveat: string }

export interface ChatResponse {
  for_you?: ForYouData | null
  domain: string
  query: string
  response: string
  company?: string
  risk?: RiskInfo
  quiz?: QuizItem
  concept_name?: string
  audio_token?: string | null
  report?: ResearchReportData
  report_id?: string | null
  fund_report?: boolean
  profile_basis?: string
  data_basis?: string
  ui_action?: string
  missing_field?: string
  corrected_query?: string
  context?: { news_headlines?: string[] } & Record<string, unknown>
  [key: string]: unknown
}

export interface HistoryTurn {
  query: string
  response: ChatResponse
  audio_token?: string | null
  quiz_answered?: boolean
  quiz_correct?: boolean
}

export interface Loan { kind?: string; emi?: number; rate_pct?: number; months_left?: number; outstanding?: number }
export interface Goal { name?: string; target?: number; years?: number; priority?: number; saved?: number }
/** All fields optional; absent/null = unknown. */
export interface FinanceProfile {
  age?: number; city?: string; city_tier?: number; employment?: string; marital_status?: string; dependents?: number
  monthly_income?: number; income_stability?: string
  expenses?: Record<string, number>; assets?: Record<string, number>
  loans?: Loan[]; credit_card_outstanding?: number; term_cover?: number; health_cover?: number
  goals?: Goal[]; risk_tolerance?: string; horizon_years?: number; tax_regime?: string; used_80c?: number; used_80d?: number
}
export interface ProfileState {
  profile: FinanceProfile
  sources: Record<string, { src: 'chat' | 'form'; at: string }>
  completeness: { pct: number; missing: string[] }
}
export interface ProfileSummary {
  snapshot?: Partial<Record<'net_worth' | 'monthly_surplus' | 'savings_rate' | 'emergency_months' | 'foir' | 'liquid', number | null>>
  health?: { score: number; coverage?: number; breakdown: { name: string; weight: number; sub: number | null; reason: string }[] } | null
  goals?: { name: string; target: number; years: number; future_target?: number; sip_needed?: number | null; on_track?: boolean | null }[]
  retirement?: Record<string, unknown> | null
  tax?: { better?: string; saving?: number } | null
}

export interface Transaction {
  id: number
  date: string
  category: string
  amount: number
  merchant: string | null
  channel: string | null
}

export interface StatementRow {
  date: string
  merchant: string
  amount: number
  direction: 'debit' | 'credit'
  category: string
}

export interface StatementPreview {
  filename: string
  format: string
  rows_total: number
  importable?: number
  rows: StatementRow[]
  skipped: number
  warnings: string[]
  period: { from: string; to: string; months: number }
  summary: {
    expenses_by_category: Record<string, number>
    monthly_avg: Record<string, number>
    total_expenses: number
    total_income: number
    avg_monthly_income: number
    emi_total: number
    investment_total: number
  }
  suggested_profile: { expenses: Record<string, number>; monthly_income: number | null }
  import_id: string
}

export interface StatementImportResult {
  imported: number
  duplicates: number
  profile_updated: boolean
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

export interface SpendingInsightsData {
  available: boolean
  reason: string | null
  period: { from: string; to: string; months: number }
  cashflow: {
    income_avg: number | null; spend_avg: number; emi_avg: number; savings_rate: number | null
    by_month: { month: string; spend: number; emi: number; net: number | null }[]
  }
  categories: {
    name: string; total: number; monthly_avg: number; share_of_spend: number; share_of_income: number | null
    trend_pct: number | null; benchmark_pct: number | null; over_benchmark: boolean
  }[]
  top_merchants: { merchant: string; total: number; count: number }[]
  recurring: { merchant: string; amount: number; months: number; category: string }[]
  unusual: { date: string; merchant: string; amount: number; category: string; why: string }[]
  suggestions: { title: string; detail: string; saving_per_month: number | null; priority: 'high' | 'medium' | 'low' }[]
  notes: string[]
}
