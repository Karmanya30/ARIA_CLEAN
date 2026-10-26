import { Landmark, GraduationCap, LineChart, Building2 } from 'lucide-react'
import './TemplateCards.css'

const TEMPLATES: Array<{ label: string; icon: React.ReactNode; blurb: string; example: string }> = [
  {
    label: 'Personal Finance',
    icon: <Landmark size={18} />,
    blurb: 'Risk profile, budget, and SIP plans tailored to your income and EMIs.',
    example: 'I earn 95000 a month, pay 8500 EMI, should I start a SIP?',
  },
  {
    label: 'Tutor',
    icon: <GraduationCap size={18} />,
    blurb: 'Explains financial concepts at your level, then quizzes what you’ve learned.',
    example: 'What is compound interest?',
  },
  {
    label: 'Market Analysis',
    icon: <LineChart size={18} />,
    blurb: 'Real Nifty, Sensex, and sector trend data, narrated in plain language.',
    example: 'How did the Nifty do this week?',
  },
  {
    label: 'Equity Research',
    icon: <Building2 size={18} />,
    blurb: 'Company fundamentals and live price data for Indian-listed stocks.',
    example: "What is TCS's current stock price?",
  },
]

/** Hero-state entry points, one per module -- shown only before the first
 * message (matches the reference: template cards disappear once a real
 * conversation starts, replaced by the thread itself). */
export function TemplateCards({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="template-cards">
      {TEMPLATES.map((t) => (
        <button key={t.label} className="template-card" onClick={() => onPick(t.example)} type="button">
          <span className="template-card-icon">{t.icon}</span>
          <span className="template-card-label">{t.label}</span>
          <span className="template-card-blurb">{t.blurb}</span>
        </button>
      ))}
    </div>
  )
}
