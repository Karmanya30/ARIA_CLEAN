import { useState } from 'react'
import { ChevronRight } from 'lucide-react'
import './ShapExplainer.css'

/** Surfaces the XGBoost risk model's real SHAP top-3 feature explanation
 * directly, instead of trusting the LLM's one-word narration paraphrase
 * of it to carry the real signal faithfully. */
export function ShapExplainer({
  label,
  topFeatures,
}: {
  label: string
  topFeatures: [string, number][]
}) {
  const [open, setOpen] = useState(false)
  if (!topFeatures?.length) return null

  return (
    <div className="shap-explainer">
      <button className="shap-toggle" onClick={() => setOpen((o) => !o)} type="button">
        <ChevronRight size={14} className={open ? 'shap-chevron open' : 'shap-chevron'} />
        Why '{label}'? <span className="shap-caption">(model explanation, not LLM-generated)</span>
      </button>
      {open && (
        <ul className="shap-list">
          {topFeatures.map(([name, contribution]) => (
            <li key={name}>
              <strong>{name.replace(/_/g, ' ')}</strong>{' '}
              {contribution > 0 ? 'pushed toward' : 'pushed away from'} <em>{label}</em>{' '}
              (SHAP contribution: <code>{contribution > 0 ? '+' : ''}{contribution.toFixed(3)}</code>)
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
