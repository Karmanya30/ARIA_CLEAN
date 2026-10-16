import { Delta } from './Delta'
import { fmtNum } from './format'
import { Sparkline } from './Sparkline'
import type { OpenStock, OverviewItem } from './types'

const SYM: Record<string, string> = { INR: '₹', USD: '$' }

export function IndexCard({ item, onOpen }: { item: OverviewItem; onOpen: OpenStock }) {
  const label = `${item.name}, ${item.change_pct > 0 ? '+' : ''}${item.change_pct.toFixed(1)}% today`
  return (
    <button type="button" className="mk-card mk-index" onClick={() => onOpen(item.symbol)} aria-label={`${label}. Open details`}>
      <span className="mk-index-name">{item.name}</span>
      <span className="mk-index-price num">{item.group === 'india' ? '' : (SYM[item.currency] ?? '')}{fmtNum(item.price)}</span>
      <span className="mk-index-delta">
        <Delta value={item.change_pct} />
        <span className="mk-faint"><Delta value={item.change} suffix="" /></span>
      </span>
      <Sparkline points={item.spark} label={label} />
    </button>
  )
}
