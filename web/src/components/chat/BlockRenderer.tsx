import type { ReactNode } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  ComposedChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AlertTriangle, Info, XCircle, Lightbulb, Cog, Link2 } from 'lucide-react'
import type {
  Block,
  BreakdownBlock,
  ChartBlock,
  ComparisonBlock,
  DefinitionBlock,
  ExplanationBlock,
  FormulaBlock,
  HintBlock,
  MCQBlockData,
  MasteryBlock,
  MetricBlock,
  RecommendationBlock,
  RiskBlock,
  TableBlock,
  TextBlock,
} from '../../types'
import { Markdown } from './Markdown'
import { QuizWidget } from './QuizWidget'
import { ShapExplainer } from './ShapExplainer'
import './BlockRenderer.css'

// Same palette as web/src/styles/tokens.css -- hardcoded hex here (not
// var(--x)) since these feed recharts' SVG fill/stroke props directly.
const PALETTE = ['#2953b8', '#0f8a5f', '#5b4fcf', '#b45309', '#0d9488', '#2563eb', '#d13438', '#8b96ab']

const TAXAL_META: Record<string, { icon: ReactNode; color: string }> = {
  Cognitive: { icon: <Lightbulb size={14} />, color: 'var(--green)' },
  Functional: { icon: <Cog size={14} />, color: 'var(--blue)' },
  Causal: { icon: <Link2 size={14} />, color: 'var(--amber)' },
}

function TextBlockView({ block }: { block: TextBlock }) {
  return <Markdown text={block.content} />
}

function MetricBlockView({ block }: { block: MetricBlock }) {
  return (
    <div className="block-metric">
      <span className="block-metric-label">{block.label}</span>
      <span className="block-metric-value">
        {block.value}
        {block.unit ? <span className="block-metric-unit"> {block.unit}</span> : null}
      </span>
    </div>
  )
}

function FormulaBlockView({ block }: { block: FormulaBlock }) {
  return (
    <div className="block-formula">
      <code>{block.expression}</code>
      {block.variables.length > 0 && <div className="block-formula-vars">{block.variables.join(' · ')}</div>}
    </div>
  )
}

function TableBlockView({ block }: { block: TableBlock }) {
  return (
    <div className="block-table-wrap">
      <table className="block-table">
        <thead>
          <tr>
            {block.columns.map((c) => (
              <th key={c}>{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, i) => (
            <tr key={i}>
              {row.map((cell, j) => (
                <td key={j}>{cell}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function BreakdownBlockView({ block }: { block: BreakdownBlock }) {
  const total = block.amounts.reduce((a, b) => a + b, 0)
  const data = block.categories
    .map((name, i) => ({ name, value: block.amounts[i] }))
    .filter((d) => d.value > 0)

  return (
    <div className="block-breakdown">
      <div className="block-breakdown-chart">
        <ResponsiveContainer width={110} height={110}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="name" innerRadius={30} outerRadius={52} strokeWidth={1} stroke="#fff">
              {data.map((_, i) => (
                <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
              ))}
            </Pie>
            <Tooltip formatter={(v) => Number(v).toLocaleString('en-IN', { maximumFractionDigits: 0 })} />
          </PieChart>
        </ResponsiveContainer>
      </div>
      <ul className="block-breakdown-list">
        {data.map((d, i) => (
          <li key={d.name}>
            <span className="block-breakdown-swatch" style={{ background: PALETTE[i % PALETTE.length] }} />
            <span className="block-breakdown-name">{d.name}</span>
            <span className="block-breakdown-value">
              {d.value.toLocaleString('en-IN', { maximumFractionDigits: 0 })}
              {total > 0 && <em> ({Math.round((d.value / total) * 100)}%)</em>}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function ChartBlockView({ block }: { block: ChartBlock }) {
  const data = block.labels.map((label, i) => ({
    label,
    value: block.data[i],
    lower: block.lower_band?.[i],
    upper: block.upper_band?.[i],
  }))

  if (block.chart_type === 'donut') {
    return (
      <div className="block-chart">
        {block.series_name && <div className="block-chart-title">{block.series_name}</div>}
        <ResponsiveContainer width="100%" height={180}>
          <PieChart>
            <Pie data={data} dataKey="value" nameKey="label" innerRadius={40} outerRadius={70}>
              {data.map((_, i) => (
                <Cell key={i} fill={PALETTE[i % PALETTE.length]} />
              ))}
            </Pie>
            <Tooltip />
          </PieChart>
        </ResponsiveContainer>
      </div>
    )
  }

  if (block.chart_type === 'bar') {
    return (
      <div className="block-chart">
        {block.series_name && <div className="block-chart-title">{block.series_name}</div>}
        <ResponsiveContainer width="100%" height={180}>
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e7f0" />
            <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#8b96ab" />
            <YAxis tick={{ fontSize: 11 }} stroke="#8b96ab" />
            <Tooltip />
            <Bar dataKey="value" fill="#2953b8" radius={[4, 4, 0, 0]} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    )
  }

  // line -- confidence band (if present) drawn as two dashed guide lines
  // around the solid value line, rather than a stacked-area trick that's
  // easy to get subtly wrong without a live render to check against.
  return (
    <div className="block-chart">
      {block.series_name && <div className="block-chart-title">{block.series_name}</div>}
      <ResponsiveContainer width="100%" height={180}>
        <ComposedChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e2e7f0" />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="#8b96ab" />
          <YAxis tick={{ fontSize: 11 }} stroke="#8b96ab" />
          <Tooltip />
          {block.upper_band && <Line dataKey="upper" stroke="#8b96ab" strokeDasharray="4 3" dot={false} name="Upper estimate" />}
          {block.lower_band && <Line dataKey="lower" stroke="#8b96ab" strokeDasharray="4 3" dot={false} name="Lower estimate" />}
          <Line dataKey="value" stroke="#2953b8" strokeWidth={2} dot={{ r: 3 }} name={block.series_name ?? 'Value'} />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

function RiskBlockView({ block }: { block: RiskBlock }) {
  return (
    <div className="block-risk">
      <div className="block-risk-head">
        <span className="block-risk-level">{block.level}</span>
        <span className="block-risk-score">{Math.round(block.score * 100)}% confidence</span>
      </div>
      <ShapExplainer label={block.level} topFeatures={block.factors.map((f) => [f.name, f.contribution])} />
    </div>
  )
}

function RecommendationBlockView({ block }: { block: RecommendationBlock }) {
  return (
    <div className="block-recommendation">
      <div className="block-recommendation-title">{block.title}</div>
      <p className="block-recommendation-rationale">{block.rationale}</p>
      {block.actions.length > 0 && (
        <ul className="block-recommendation-actions">
          {block.actions.map((action, i) => (
            <li key={i}>{action}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

function ComparisonBlockView({ block }: { block: ComparisonBlock }) {
  const metricKeys = Array.from(new Set(block.rows.flatMap((row) => Object.keys(row.metrics))))
  return (
    <div className="block-comparison">
      <div className="block-comparison-title">{block.title}</div>
      <div className="block-table-wrap">
        <table className="block-table">
          <thead>
            <tr>
              <th />
              {metricKeys.map((k) => (
                <th key={k}>{k}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {block.rows.map((row) => (
              <tr key={row.name}>
                <td className="block-comparison-name">{row.name}</td>
                {metricKeys.map((k) => (
                  <td key={k}>{row.metrics[k] ?? '—'}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

const ALERT_ICON: Record<string, ReactNode> = {
  info: <Info size={16} />,
  warning: <AlertTriangle size={16} />,
  error: <XCircle size={16} />,
}

function AlertBlockView({ block }: { block: { severity: 'info' | 'warning' | 'error'; message: string } }) {
  return (
    <div className={`block-alert block-alert-${block.severity}`}>
      {ALERT_ICON[block.severity]}
      <span>{block.message}</span>
    </div>
  )
}

function ExplanationBlockView({ block }: { block: ExplanationBlock }) {
  const meta = TAXAL_META[block.label] ?? { icon: null, color: 'var(--accent)' }
  return (
    <div className="block-explanation" style={{ borderLeftColor: meta.color }}>
      <div className="block-explanation-label" style={{ color: meta.color }}>
        {meta.icon}
        {block.label}
      </div>
      <Markdown text={block.content} />
    </div>
  )
}

function DefinitionBlockView({ block }: { block: DefinitionBlock }) {
  return (
    <div className="block-definition">
      <div className="block-definition-term">{block.term}</div>
      <p>{block.definition}</p>
    </div>
  )
}

function HintBlockView({ block }: { block: HintBlock }) {
  return (
    <div className="block-hint">
      <span className="block-hint-badge">Hint {block.level}</span>
      <span>{block.content}</span>
    </div>
  )
}

function MasteryBlockView({ block }: { block: MasteryBlock }) {
  return (
    <div className="block-mastery">
      <div className="block-mastery-head">
        <span>{block.topic}</span>
        <span className="block-mastery-pct">{Math.round(block.score * 100)}%</span>
      </div>
      <div className="block-mastery-bar">
        <div className="block-mastery-bar-fill" style={{ width: `${Math.min(100, block.score * 100)}%` }} />
      </div>
    </div>
  )
}

/** Dispatches one block to its renderer. mcq is handled by the caller
 * (BlockList below), not here, since QuizWidget needs sessionId/seed/
 * onAnswered props BlockRenderer itself doesn't have. */
function renderBlock(block: Block, key: number): ReactNode {
  switch (block.type) {
    case 'text':
      return <TextBlockView key={key} block={block} />
    case 'metric':
      return <MetricBlockView key={key} block={block} />
    case 'formula':
      return <FormulaBlockView key={key} block={block} />
    case 'table':
      return <TableBlockView key={key} block={block} />
    case 'breakdown':
      return <BreakdownBlockView key={key} block={block} />
    case 'chart':
      return <ChartBlockView key={key} block={block} />
    case 'risk':
      return <RiskBlockView key={key} block={block} />
    case 'recommendation':
      return <RecommendationBlockView key={key} block={block} />
    case 'comparison':
      return <ComparisonBlockView key={key} block={block} />
    case 'alert':
      return <AlertBlockView key={key} block={block} />
    case 'explanation':
      return <ExplanationBlockView key={key} block={block} />
    case 'definition':
      return <DefinitionBlockView key={key} block={block} />
    case 'hint':
      return <HintBlockView key={key} block={block} />
    case 'mastery':
      return <MasteryBlockView key={key} block={block} />
    case 'mcq':
      return null // rendered separately by BlockList, see below
    default:
      return null
  }
}

/** Renders a full `blocks` list for one response, including the `mcq`
 * block (which needs the extra quiz-answering props QuizWidget takes) --
 * this is what MessageBubble.tsx should call, not renderBlock directly. */
export function BlockList({
  blocks,
  sessionId,
  seed,
  quizAnswered,
  quizCorrect,
  onQuizAnswered,
}: {
  blocks: Block[]
  sessionId: string
  seed: string
  quizAnswered?: boolean
  quizCorrect?: boolean
  onQuizAnswered: (correct: boolean) => void
}) {
  return (
    <div className="block-list">
      {blocks.map((block, i) => {
        if (block.type === 'mcq') {
          const mcq = block as MCQBlockData
          if (quizAnswered) {
            return (
              <div key={i} className={quizCorrect ? 'quiz-result quiz-correct' : 'quiz-result quiz-incorrect'}>
                {quizCorrect ? `Correct! ${mcq.explanation}` : `Not quite. ${mcq.explanation}`}
              </div>
            )
          }
          return (
            <QuizWidget
              key={i}
              quiz={mcq}
              sessionId={sessionId}
              seed={seed}
              onAnswered={onQuizAnswered}
            />
          )
        }
        return renderBlock(block, i)
      })}
    </div>
  )
}
