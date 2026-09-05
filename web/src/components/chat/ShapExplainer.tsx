import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import './ShapExplainer.css'

/** Surfaces the XGBoost risk model's real SHAP top-3 feature explanation
 * directly, instead of trusting the LLM's one-word narration paraphrase
 * of it to carry the real signal faithfully.
 *
 * Stage 13: upgraded from a plain <ul> list to a real horizontal bar
 * chart -- same prop interface as before (label + topFeatures tuples), so
 * MessageBubble.tsx's existing direct usage (the legacy `response.risk`
 * path) needs no changes, and BlockRenderer.tsx's `risk` block wraps this
 * same component rather than a second implementation. */
export function ShapExplainer({
  label,
  topFeatures,
}: {
  label: string
  topFeatures: [string, number][]
}) {
  const [open, setOpen] = useState(false)
  if (!topFeatures?.length) return null

  const data = topFeatures.map(([name, contribution]) => ({
    name: name.replace(/_/g, ' '),
    contribution,
  }))

  return (
    <div className="shap-explainer">
      <button className="shap-toggle" onClick={() => setOpen((o) => !o)} type="button">
        <ChevronRight size={14} className={open ? 'shap-chevron open' : 'shap-chevron'} />
        Why '{label}'? <span className="shap-caption">(model explanation, not LLM-generated)</span>
      </button>
      {open && (
        <div className="shap-chart">
          <ResponsiveContainer width="100%" height={Math.max(60, data.length * 36)}>
            <BarChart data={data} layout="vertical" margin={{ top: 4, right: 24, bottom: 4, left: 4 }}>
              <XAxis type="number" tick={{ fontSize: 11 }} stroke="#8b96ab" />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={110} stroke="#8b96ab" />
              <Tooltip
                formatter={(value) => [Number(value).toFixed(3), 'SHAP contribution']}
                contentStyle={{ fontSize: 12, borderRadius: 8 }}
              />
              <Bar dataKey="contribution" radius={[0, 4, 4, 0]}>
                {data.map((d) => (
                  <Cell key={d.name} fill={d.contribution >= 0 ? '#0f8a5f' : '#d13438'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
          <ul className="shap-legend">
            {data.map((d) => (
              <li key={d.name}>
                <strong>{d.name}</strong>{' '}
                {d.contribution >= 0 ? 'pushed toward' : 'pushed away from'} <em>{label}</em>{' '}
                (<code>{d.contribution > 0 ? '+' : ''}{d.contribution.toFixed(3)}</code>)
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
