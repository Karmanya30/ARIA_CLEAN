import './NewsFeed.css'
import { BrandMark } from '../../../../components/brand/BrandLogo'
import { useCallback, useId, useMemo, useRef, useState } from 'react'
import {
  ArrowLeft,
  ArrowRight,
  ExternalLink,
  Minus,
  Search,
  TrendingDown,
  TrendingUp,
  X,
  BarChart2,
  MessageSquare,
  Newspaper,
  Building2,
  Globe,
  ChevronDown,
  Filter,
  RefreshCw,
  Clock,
  Tag,
} from 'lucide-react'
import { api } from '../../api'
import { fmtAge } from './format'
import { DataProv, Provenance } from './Provenance'
import type { News, OpenStock } from './types'

/* ── Constants ─────────────────────────────────────────────────────────── */
const PAGE_SIZE = 10

const TONE_META = {
  positive: { Icon: TrendingUp,   cls: 'mk-up',   label: 'Positive' },
  neutral:  { Icon: Minus,        cls: 'mk-flat',  label: 'Neutral'  },
  negative: { Icon: TrendingDown, cls: 'mk-down',  label: 'Negative' },
} as const

const NEWS_CATEGORIES = [
  { id: '',         label: 'All News'  },
  { id: 'positive', label: 'Bullish'   },
  { id: 'neutral',  label: 'Neutral'   },
  { id: 'negative', label: 'Bearish'   },
] as const

const DAILY_ASKS = [
  { id: 'top',       Icon: Newspaper,   label: 'Top news today',      q: 'What were the top market news stories today? Give me a brief summary of the most important headlines.' },
  { id: 'market',    Icon: BarChart2,   label: 'Market today',        q: 'How did the Indian stock market perform today? Summarise NSE/BSE movements, sector performance, and overall sentiment.' },
  { id: 'corporate', Icon: Building2,   label: 'Corporate news',      q: 'What are the most important corporate news and earnings announcements today? Any major deals, mergers, or management changes?' },
  { id: 'economy',   Icon: Globe,       label: 'Economy & macro',     q: 'What are the key economic and macroeconomic news today? Any RBI, inflation, GDP, or government policy updates?' },
  { id: 'fii',       Icon: TrendingUp,  label: 'FII / DII activity',  q: 'What is the latest FII and DII activity in the Indian market today? Are institutions buying or selling?' },
] as const

type NewsItem = News['items'][number]
type ToneFilter = '' | 'positive' | 'neutral' | 'negative'

/* ── Sentiment Bar ─────────────────────────────────────────────────────── */
function SentimentBar({ net }: { net: number }) {
  const normalised = Math.round(Math.max(-1, Math.min(1, net)) * 50 + 50)
  const tone = net > 0.1 ? 'positive' : net < -0.1 ? 'negative' : 'neutral'
  return (
    <div className="nw-sent-wrap" role="img" aria-label={`Sentiment ${normalised}/100`}>
      <div className="nw-sent-track">
        <div className={`nw-sent-fill nw-sent-${tone}`} style={{ width: `${normalised}%` }} />
        <div className="nw-sent-mid" />
      </div>
      <div className="nw-sent-labels">
        <span>Bearish</span>
        <span className={`nw-sent-val nw-sent-${tone}`}>{normalised}/100</span>
        <span>Bullish</span>
      </div>
    </div>
  )
}

/* ── Gauge SVG ─────────────────────────────────────────────────────────── */
function SentGauge({ net }: { net: number }) {
  const normalised = Math.round(Math.max(-1, Math.min(1, net)) * 50 + 50)
  const tone = net > 0.1 ? 'positive' : net < -0.1 ? 'negative' : 'neutral'
  const toneColor = tone === 'positive' ? 'var(--up)' : tone === 'negative' ? 'var(--down)' : 'var(--ink-muted)'
  const angle = (normalised / 100) * 180 - 180
  const rad = (angle * Math.PI) / 180
  const nx = 100 + 72 * Math.cos(rad)
  const ny = 100 + 72 * Math.sin(rad)
  return (
    <div className="nw-gauge-wrap">
      <svg viewBox="0 0 200 110" className="nw-gauge-svg" aria-hidden="true">
        <defs>
          <linearGradient id="gaugeGrad2" x1="0%" y1="0%" x2="100%" y2="0%">
            <stop offset="0%"   stopColor="var(--down)" />
            <stop offset="50%"  stopColor="var(--border-strong)" />
            <stop offset="100%" stopColor="var(--up)" />
          </linearGradient>
        </defs>
        <path d="M 12 100 A 88 88 0 0 1 188 100" fill="none" stroke="url(#gaugeGrad2)" strokeWidth="14" strokeLinecap="round" />
        <line x1="100" y1="100" x2={nx} y2={ny} stroke={toneColor} strokeWidth="2.5" strokeLinecap="round" />
        <circle cx="100" cy="100" r="5" fill={toneColor} />
        <text x="16" y="108" fontSize="9"  fill="var(--down)" fontWeight="600">Bear</text>
        <text x="157" y="108" fontSize="9" fill="var(--up)"   fontWeight="600">Bull</text>
        <text x="100" y="82" textAnchor="middle" fontSize="22" fontWeight="700" fill="var(--ink)">{normalised}</text>
        <text x="100" y="95" textAnchor="middle" fontSize="9"  fill="var(--ink-muted)">/ 100</text>
      </svg>
    </div>
  )
}

/* ── News Detail Modal ─────────────────────────────────────────────────── */
function NewsModal({
  item, engine, onClose, onOpen,
}: {
  item: NewsItem; engine: string; onClose: () => void; onOpen: OpenStock; onAsk: (q: string) => void
}) {
  const dlg = useRef<HTMLDialogElement>(null)
  const [question, setQuestion] = useState('')
  const [thread, setThread] = useState<{ q: string; a: string; loading?: boolean }[]>([])
  const threadRef = useRef<HTMLDivElement>(null)

  const opened = useRef(false)
  if (!opened.current) {
    opened.current = true
    requestAnimationFrame(() => { if (dlg.current && !dlg.current.open) dlg.current.showModal() })
  }

  const { Icon, label } = TONE_META[item.tone]

  async function ask(q: string) {
    if (!q.trim()) return
    const idx = thread.length
    setThread((t) => [...t, { q, a: '', loading: true }])
    setQuestion('')
    setTimeout(() => threadRef.current?.scrollTo({ top: 9999, behavior: 'smooth' }), 80)
    try {
      const res = await api.sendMessage(
        q,
        'news-' + Date.now(),
        'Normal Mode',
        false,
        `Market news item.\nHeadline: "${item.title}"\nSource: ${item.source}\nSentiment: ${item.tone} (score: ${item.net.toFixed(2)})\nRelated stocks: ${item.symbols.join(', ') || 'none'}`,
      )
      setThread((t) => t.map((x, i) => (i === idx ? { ...x, a: res.response, loading: false } : x)))
      setTimeout(() => threadRef.current?.scrollTo({ top: 9999, behavior: 'smooth' }), 80)
    } catch {
      setThread((t) => t.map((x, i) => (i === idx ? { ...x, a: 'Could not get a response. Please try again.', loading: false } : x)))
    }
  }

  const quickQs = [
    `What does this mean for ${item.symbols[0]?.replace(/\.(NS|BO)$/, '') ?? 'the market'}?`,
    'What is the likely short-term market impact?',
    'Should I buy, hold, or sell based on this news?',
    'Give me the bull and bear case.',
    'What sector is most affected?',
  ]

  return (
    <dialog
      ref={dlg}
      className="nw-modal"
      aria-labelledby="nw-modal-title"
      onCancel={(e) => (e.preventDefault(), onClose())}
      onClick={(e) => e.target === dlg.current && onClose()}
    >
      <div className="nw-modal-body">
        <div className="nw-modal-head">
          <div className={`nw-tone-badge nw-tone-${item.tone}`}>
            <Icon size={13} aria-hidden="true" /> {label} sentiment
          </div>
          <button className="sd-x" type="button" onClick={onClose} aria-label="Close">✕</button>
        </div>

        <article className="nw-article">
          <h2 id="nw-modal-title">{item.title}</h2>
          <div className="nw-article-meta">
            <span className="nw-source">{item.source}</span>
            <span aria-hidden="true">·</span>
            <span><Clock size={11} style={{ verticalAlign: 'middle', marginRight: 2 }} />{fmtAge(item.age_hours)}</span>
            {item.sources > 1 && (<><span aria-hidden="true">·</span><span className="mk-chip">{item.sources} outlets</span></>)}
          </div>
          <a href={item.url} target="_blank" rel="noopener noreferrer" className="nw-read-link btn">
            <ExternalLink size={14} aria-hidden="true" /> Read full article
          </a>
        </article>

        <section className="nw-sent-section" aria-label="Sentiment analysis">
          <div className="sd-h">
            <h3><BarChart2 size={16} aria-hidden="true" /> Sentiment Analysis</h3>
            <Provenance kind="ai" />
          </div>
          <SentGauge net={item.net} />
          <SentimentBar net={item.net} />
          <p className="note">Tone classified by <strong>{engine}</strong> — AI-generated. Treat as a signal, not a fact.</p>
        </section>

        {item.symbols.length > 0 && (
          <section aria-label="Related stocks">
            <h3 className="nw-sec-h"><Tag size={14} style={{ marginRight: 4 }} />Related stocks</h3>
            <div className="nw-sym-chips">
              {item.symbols.map((s) => (
                <button key={s} type="button" className="mk-chip mk-chipbtn nw-sym"
                  onClick={() => { onOpen(s); onClose() }}>
                  {s.replace(/\.(NS|BO)$/, '')}
                </button>
              ))}
            </div>
          </section>
        )}

        <section className="nw-ask-section" aria-label="Ask ARIA about this news">
          <div className="sd-h">
            <h3><BrandMark className="aria-news-mark" /> Ask ARIA about this news</h3>
          </div>
          <div className="nw-quick-qs">
            {quickQs.map((q) => (
              <button key={q} type="button" className="mk-chip mk-chipbtn nw-q-chip" onClick={() => ask(q)}>{q}</button>
            ))}
          </div>
          {thread.length > 0 && (
            <div className="nw-thread" ref={threadRef} aria-live="polite">
              {thread.map((t, i) => (
                <div key={i} className="nw-turn">
                  <p className="nw-q">{t.q}</p>
                  {t.loading
                    ? <span className="mk-skel" style={{ '--h': '80px' } as React.CSSProperties} role="status" aria-label="ARIA is thinking" />
                    : <div className="nw-answer"><BrandMark className="aria-news-mark nw-aria-icon" /><p>{t.a}</p></div>
                  }
                </div>
              ))}
            </div>
          )}
          <form className="nw-ask-form" onSubmit={(e) => { e.preventDefault(); ask(question) }}>
            <input className="ix-in" type="text" placeholder="Ask anything about this news…"
              value={question} onChange={(e) => setQuestion(e.target.value)} aria-label="Your question" />
            <button type="submit" className="btn primary" disabled={!question.trim()}>Ask</button>
          </form>
          <p className="note" style={{ marginTop: 8 }}>ARIA is an AI — responses may be incomplete. Not financial advice.</p>
        </section>
      </div>
    </dialog>
  )
}

/* ── Global News Q&A Panel ─────────────────────────────────────────────── */
function NewsQAPanel({ onClose, initialQ, headlines }: {
  onClose: () => void; initialQ?: string; headlines: string[]
}) {
  const [question, setQuestion] = useState('')
  const [thread, setThread] = useState<{ q: string; a: string; loading?: boolean }[]>([])
  const threadRef = useRef<HTMLDivElement>(null)

  async function ask(q: string) {
    if (!q.trim()) return
    const idx = thread.length
    setThread((t) => [...t, { q, a: '', loading: true }])
    setQuestion('')
    setTimeout(() => threadRef.current?.scrollTo({ top: 9999, behavior: 'smooth' }), 80)
    try {
      const ctx = headlines.length
        ? `\n\nCurrent market news headlines:\n${headlines.slice(0, 15).map((h, i) => `${i + 1}. ${h}`).join('\n')}`
        : ''
      const res = await api.sendMessage(
        q,
        'news-qa-' + Date.now(),
        'Normal Mode',
        false,
        ctx.trim() || undefined,
      )
      setThread((t) => t.map((x, i) => (i === idx ? { ...x, a: res.response, loading: false } : x)))
      setTimeout(() => threadRef.current?.scrollTo({ top: 9999, behavior: 'smooth' }), 80)
    } catch {
      setThread((t) => t.map((x, i) => (i === idx ? { ...x, a: 'Could not get a response. Please try again.', loading: false } : x)))
    }
  }

  const fired = useRef(false)
  if (initialQ && !fired.current) { fired.current = true; requestAnimationFrame(() => ask(initialQ)) }

  return (
    <div className="nw-qa-panel">
      <div className="nw-qa-header">
        <BrandMark className="aria-news-mark" />
        <span>Ask ARIA about Today's News</span>
        <button type="button" className="sd-x nw-qa-close" onClick={onClose} aria-label="Close Q&A">✕</button>
      </div>
      <div className="nw-qa-thread" ref={threadRef} aria-live="polite">
        {thread.length === 0 && (
          <div className="nw-qa-empty">
            <Newspaper size={28} aria-hidden="true" />
            <p>Ask me anything about today's market news</p>
          </div>
        )}
        {thread.map((t, i) => (
          <div key={i} className="nw-turn">
            <p className="nw-q">{t.q}</p>
            {t.loading
              ? <span className="mk-skel" style={{ '--h': '80px' } as React.CSSProperties} role="status" />
              : <div className="nw-answer"><BrandMark className="aria-news-mark nw-aria-icon" /><p>{t.a}</p></div>
            }
          </div>
        ))}
      </div>
      <form className="nw-qa-form" onSubmit={(e) => { e.preventDefault(); ask(question) }}>
        <input className="ix-in" type="text"
          placeholder="Ask about today's news, sentiment, sector trends…"
          value={question} onChange={(e) => setQuestion(e.target.value)} aria-label="Ask about news" />
        <button type="submit" className="btn primary" disabled={!question.trim()}>
          <MessageSquare size={14} /> Ask
        </button>
      </form>
    </div>
  )
}

/* ── Single news row ───────────────────────────────────────────────────── */
function NewsRow({
  item, engine, onOpenModal, onOpen, onAsk, index,
}: {
  item: NewsItem; engine: string; onOpenModal: (item: NewsItem) => void
  onOpen: OpenStock; onAsk: (q: string) => void; index: number
}) {
  const { Icon, cls } = TONE_META[item.tone]
  const isFresh = item.age_hours < 2
  return (
    <li className={`nw-row${isFresh ? ' nw-row-fresh' : ''}`}>
      <span className="nw-row-num" aria-hidden="true">{index + 1}</span>
      <div className="nw-row-main">
        <button type="button" className="mk-headline nw-title-btn" onClick={() => onOpenModal(item)}>
          {isFresh && <span className="nw-fresh-dot" aria-label="Fresh — published in last 2 hours" />}
          {item.title}
        </button>
        <div className="mk-meta">
          <span className="nw-source-tag">{item.source}</span>
          <span aria-hidden="true">·</span>
          <span><Clock size={10} style={{ verticalAlign: 'middle', marginRight: 2 }} />{fmtAge(item.age_hours)}</span>
          {item.sources > 1 && <span className="mk-chip">{item.sources} outlets</span>}
          <span className={`mk-chip mk-tone ${cls}`} title={`Sentiment via ${engine}`} aria-label={`${item.tone} sentiment`}>
            <Icon size={11} aria-hidden="true" /> {item.tone}
          </span>
          {item.symbols.slice(0, 3).map((s) => (
            <button key={s} type="button" className="mk-chip mk-chipbtn" onClick={() => onOpen(s)}>
              {s.replace(/\.(NS|BO)$/, '')}
            </button>
          ))}
        </div>
      </div>
      <div className="nw-row-actions">
        <button type="button" className="nw-open-btn" onClick={() => onOpenModal(item)} aria-label={`Analyse: ${item.title}`}>
          <BarChart2 size={12} /> Analyse
        </button>
        <button type="button" className="mk-ask"
          onClick={() => onAsk(`What does this headline mean for my investments? ${item.title}`)}>
          Quick ask
        </button>
      </div>
    </li>
  )
}

/* ── Main NewsFeed ─────────────────────────────────────────────────────── */
interface Res<T> { data: T | null; error: string | null; loading: boolean; stale: boolean }

export function NewsFeed({
  res, onOpen, onAsk,
}: {
  res: Res<News>; onOpen: OpenStock; onAsk: (q: string) => void
}) {
  const searchId = useId()
  const [search, setSearch]   = useState('')
  const [tone, setTone]       = useState<ToneFilter>('')
  const [company, setCompany] = useState('')
  const [page, setPage]       = useState(0)
  const [modal, setModal]     = useState<NewsItem | null>(null)
  const [qaOpen, setQaOpen]   = useState(false)
  const [qaInitQ, setQaInitQ] = useState<string | undefined>()
  const [qaKey, setQaKey]     = useState(0)
  const [showMore, setShowMore] = useState(false)

  const data = res.data

  const allCompanies = useMemo(() => {
    if (!data) return []
    const syms = new Set<string>()
    data.items.forEach((n) => n.symbols.forEach((s) => syms.add(s.replace(/\.(NS|BO)$/, ''))))
    return [...syms].sort()
  }, [data])

  const filtered = useMemo(() => {
    if (!data) return []
    return data.items.filter((n) => {
      if (tone && n.tone !== tone) return false
      if (company) {
        const sym = company.toLowerCase()
        if (!n.symbols.some((s) => s.toLowerCase().includes(sym)) && !n.title.toLowerCase().includes(sym)) return false
      }
      if (search) {
        const q = search.toLowerCase()
        if (!n.title.toLowerCase().includes(q) && !n.source.toLowerCase().includes(q) &&
          !n.symbols.some((s) => s.toLowerCase().includes(q))) return false
      }
      return true
    })
  }, [data, search, tone, company])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const safePage   = Math.min(page, totalPages - 1)
  const visible    = filtered.slice(safePage * PAGE_SIZE, (safePage + 1) * PAGE_SIZE)
  const resetPage  = useCallback(() => setPage(0), [])

  function clearFilters() { setSearch(''); setTone(''); setCompany(''); setPage(0) }
  const hasFilters = search || tone || company

  function openQA(q?: string) { setQaInitQ(q); setQaKey((k) => k + 1); setQaOpen(true) }

  const headlines = data?.items.map((n) => n.title) ?? []

  /* sentiment aggregates */
  const sentStats = useMemo(() => {
    if (!data || !data.items.length) return null
    const pos = data.items.filter(n => n.tone === 'positive').length
    const neg = data.items.filter(n => n.tone === 'negative').length
    const neu = data.items.filter(n => n.tone === 'neutral').length
    const total = data.items.length
    const avgNet = data.items.reduce((s, n) => s + n.net, 0) / total
    const overallTone = avgNet > 0.05 ? 'positive' : avgNet < -0.05 ? 'negative' : 'neutral'
    return { pos, neg, neu, total, avgNet, overallTone }
  }, [data])

  /* page number helpers */
  function pageNums(current: number, total: number): (number | 'gap')[] {
    if (total <= 7) return Array.from({ length: total }, (_, i) => i)
    const set = new Set([0, total - 1, current, current - 1, current + 1].filter(n => n >= 0 && n < total))
    const sorted = [...set].sort((a, b) => a - b)
    const result: (number | 'gap')[] = []
    sorted.forEach((n, i) => {
      if (i > 0 && n - (sorted[i - 1] as number) > 1) result.push('gap')
      result.push(n)
    })
    return result
  }

  return (
    <section className="mk-card mk-panel nw-panel" aria-label="Market news" aria-busy={res.loading}>

      {/* ── Header ── */}
      <header className="mk-panel-h nw-header">
        <div className="nw-title-row">
          <Newspaper size={18} aria-hidden="true" className="nw-header-icon" />
          <h2>Market News</h2>
          {data && (
            <span className="nw-count">
              {filtered.length} article{filtered.length !== 1 ? 's' : ''}{hasFilters ? ' (filtered)' : ` of ${data.items.length}`}
            </span>
          )}
        </div>
        <button type="button" className="nw-qa-btn" onClick={() => openQA()} aria-expanded={qaOpen}>
          <MessageSquare size={14} /> Ask ARIA
        </button>
      </header>

      {/* ── Daily question buttons ── */}
      <div className="nw-daily-asks" role="group" aria-label="Daily market questions">
        <span className="nw-daily-label">Daily insights:</span>
        {DAILY_ASKS.map((a) => (
          <button key={a.id} type="button" className="nw-daily-btn" onClick={() => openQA(a.q)}>
            <a.Icon size={13} aria-hidden="true" /> {a.label}
          </button>
        ))}
      </div>

      {/* ── Aggregate sentiment ── */}
      {sentStats && !res.loading && (
        <div className="nw-agg-sent">
          <div className="nw-agg-header">
            <BarChart2 size={14} aria-hidden="true" />
            <span>Overall sentiment — {sentStats.total} stories</span>
            <span className={`nw-tone-badge nw-tone-${sentStats.overallTone}`}>
              {sentStats.overallTone === 'positive' ? 'Bullish' : sentStats.overallTone === 'negative' ? 'Bearish' : 'Neutral'}
            </span>
          </div>
          <div className="nw-agg-bars">
            <div className="nw-agg-bar-row">
              <span className="mk-up nw-agg-label">Bullish</span>
              <div className="nw-agg-track"><div className="nw-agg-fill up" style={{ width: `${(sentStats.pos / sentStats.total) * 100}%` }} /></div>
              <span className="nw-agg-count">{sentStats.pos}</span>
            </div>
            <div className="nw-agg-bar-row">
              <span className="nw-agg-label" style={{ color: 'var(--ink-muted)' }}>Neutral</span>
              <div className="nw-agg-track"><div className="nw-agg-fill neu" style={{ width: `${(sentStats.neu / sentStats.total) * 100}%` }} /></div>
              <span className="nw-agg-count">{sentStats.neu}</span>
            </div>
            <div className="nw-agg-bar-row">
              <span className="mk-down nw-agg-label">Bearish</span>
              <div className="nw-agg-track"><div className="nw-agg-fill down" style={{ width: `${(sentStats.neg / sentStats.total) * 100}%` }} /></div>
              <span className="nw-agg-count">{sentStats.neg}</span>
            </div>
          </div>
        </div>
      )}

      {/* ── Filters ── */}
      <div className="nw-filters">
        <div className="nw-search-wrap">
          <Search size={15} className="nw-search-icon" aria-hidden="true" />
          <input id={searchId} type="search" className="nw-search-input"
            placeholder="Search news, source, ticker…" value={search}
            onChange={(e) => { setSearch(e.target.value); resetPage() }} aria-label="Search news" />
          {search && (
            <button type="button" className="nw-search-clear" onClick={() => { setSearch(''); resetPage() }} aria-label="Clear search">
              <X size={13} />
            </button>
          )}
        </div>
        <div className="nw-filter-row">
          {NEWS_CATEGORIES.map((c) => (
            <button key={c.id} type="button" className="mk-pillbtn nw-filter-btn"
              aria-pressed={tone === c.id} onClick={() => { setTone(c.id as ToneFilter); resetPage() }}>
              {c.id && <span className={`nw-filter-dot nw-filter-dot--${c.id}`} aria-hidden="true" />}
              {c.label}
            </button>
          ))}
          <button type="button" className="mk-pillbtn nw-filter-btn nw-filter-more"
            aria-pressed={showMore} onClick={() => setShowMore(!showMore)}>
            <Filter size={12} /> More filters
            <ChevronDown size={11} style={{ transition: 'transform .2s', transform: showMore ? 'rotate(180deg)' : 'none' }} />
          </button>
        </div>
        {showMore && allCompanies.length > 0 && (
          <div className="nw-filter-extended">
            <div className="nw-filter-group">
              <label className="nw-filter-label"><Building2 size={12} /> Company / Ticker</label>
              <select className="nw-company-select" value={company}
                onChange={(e) => { setCompany(e.target.value); resetPage() }} aria-label="Filter by company">
                <option value="">All companies</option>
                {allCompanies.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          </div>
        )}
        {hasFilters && (
          <button type="button" className="nw-clear-btn" onClick={clearFilters}>
            <X size={12} aria-hidden="true" /> Clear filters
          </button>
        )}
      </div>

      {/* ── Q&A Panel ── */}
      {qaOpen && (
        <NewsQAPanel key={qaKey} onClose={() => setQaOpen(false)} initialQ={qaInitQ} headlines={headlines} />
      )}

      {/* ── Content ── */}
      {data ? (
        <>
          {res.stale && (
            <p className="mk-note" role="status">
              <RefreshCw size={11} style={{ verticalAlign: 'middle', marginRight: 4 }} /> Showing cached news. Refreshing…
            </p>
          )}
          {filtered.length === 0 ? (
            <div className="nw-empty">
              <Search size={28} aria-hidden="true" />
              <p>No news matches your filters.</p>
              <button type="button" className="btn" onClick={clearFilters}>Clear filters</button>
            </div>
          ) : (
            <ul className="mk-news nw-list">
              {visible.map((n, i) => (
                <NewsRow key={n.url} item={n} engine={data.engine}
                  onOpenModal={setModal} onOpen={onOpen} onAsk={onAsk}
                  index={safePage * PAGE_SIZE + i} />
              ))}
            </ul>
          )}

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="nw-pager" role="navigation" aria-label="News pages">
              <button type="button" className="nw-page-btn" disabled={safePage === 0}
                onClick={() => setPage((p) => Math.max(0, p - 1))} aria-label="Previous page">
                <ArrowLeft size={15} /> Prev
              </button>
              <div className="nw-page-nums">
                {pageNums(safePage, totalPages).map((n, i) =>
                  n === 'gap'
                    ? <span key={`gap-${i}`} className="nw-ellipsis">…</span>
                    : <button key={n} type="button"
                        className={`nw-page-num${n === safePage ? ' active' : ''}`}
                        onClick={() => setPage(n)} aria-label={`Page ${n + 1}`}
                        aria-current={n === safePage ? 'page' : undefined}>{n + 1}</button>
                )}
              </div>
              <button type="button" className="nw-page-btn" disabled={safePage >= totalPages - 1}
                onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))} aria-label="Next page">
                Next <ArrowRight size={15} />
              </button>
            </div>
          )}

          <footer className="mk-panel-f">
            <DataProv meta={data.meta} />
            <Provenance kind="ai" />
          </footer>
        </>
      ) : res.loading ? (
        <div className="mk-skel-stack" role="status" aria-label="Loading market news">
          {[0, 1, 2, 3, 4, 5].map((i) => <span key={i} className="mk-skel" style={{ '--h': '60px' } as React.CSSProperties} />)}
        </div>
      ) : (
        <p className="mk-empty" role="status">Market news is unavailable right now. We will keep retrying automatically.</p>
      )}

      {/* Detail modal */}
      {modal && (
        <NewsModal item={modal} engine={data?.engine ?? 'AI'}
          onClose={() => setModal(null)} onOpen={onOpen}
          onAsk={(q) => { onAsk(q); setModal(null) }} />
      )}
    </section>
  )
}
