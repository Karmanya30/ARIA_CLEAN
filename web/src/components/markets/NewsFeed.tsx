import { Minus, TrendingDown, TrendingUp } from 'lucide-react'
import { fmtAge } from './format'
import { Panel, type Res } from './Panel'
import type { News, OpenStock } from './types'

const TONE = { positive: [TrendingUp, 'mk-up'], neutral: [Minus, 'mk-flat'], negative: [TrendingDown, 'mk-down'] } as const

export function NewsFeed({ res, onOpen, onAsk }: { res: Res<News>; onOpen: OpenStock; onAsk: (q: string) => void }) {
  return (
    <Panel title="Market news" res={res} minH={560} ai>
      {(d) => (
        <ul className="mk-news">
          {d.items.slice(0, 8).map((n) => {
            const [Icon, cls] = TONE[n.tone]
            return (
              <li key={n.url}>
                <a href={n.url} target="_blank" rel="noopener noreferrer" className="mk-headline">{n.title}</a>
                <div className="mk-meta">
                  <span>{n.source}</span><span aria-hidden="true">·</span><span>{fmtAge(n.age_hours)}</span>
                  {n.sources > 1 && <span className="mk-chip">{n.sources} outlets</span>}
                  <span className={`mk-chip mk-tone ${cls}`} title={`AI tone via ${d.engine}`}><Icon size={12} aria-hidden="true" />{n.tone}<span className="sr-only"> (AI, {d.engine})</span></span>
                  {n.symbols.slice(0, 3).map((s) => <button key={s} type="button" className="mk-chip mk-chipbtn" onClick={() => onOpen(s)}>{s.replace(/\.(NS|BO)$/, '')}</button>)}
                </div>
                <button type="button" className="mk-ask" onClick={() => onAsk('What does this headline mean for my investments? ' + n.title)}>Ask ARIA what this means</button>
              </li>
            )
          })}
        </ul>
      )}
    </Panel>
  )
}
