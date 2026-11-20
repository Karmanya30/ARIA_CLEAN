import { useCallback, useEffect, useState } from 'react'
import {
  Activity, ArrowLeft, ChevronsLeft, Compass, FileText, LineChart, Menu, MessageCircle, MessageSquareHeart, Plus, Settings,
  TrendingUp, User, X,
} from 'lucide-react'
import { BrandLogo, BrandMark } from '../../components/brand/BrandLogo'
import { ChatTab } from '../v2/components/chat/ChatTab'
import { ProfileTab } from '../v2/components/profile/ProfileTab'
import { ResearchTab } from '../v2/components/research/ResearchTab'
import { IntelligenceTab } from '../v2/components/research/IntelligenceTab'
import { ProgressTab } from '../v2/components/progress/ProgressTab'
import { SettingsTab } from '../v2/components/settings/SettingsTab'
import { FeedbackTab } from '../../components/feedback/FeedbackTab'
import { ModeToggle } from '../v2/components/ModeToggle'
import { MarketsTab } from '../v2/components/markets/MarketsTab'
import { TickerTape } from '../v2/components/markets/TickerTape'
import { ExploreTab } from '../v2/components/explore/ExploreTab'
import { GlobalSearch } from '../v2/components/explore/GlobalSearch'
import { InstrumentDrawer } from '../v2/components/explore/InstrumentDrawer'
import { DisclaimerStrip } from '../v2/components/disclaimer/DisclaimerStrip'
import { DisclaimersPage } from '../v2/components/disclaimer/DisclaimersPage'
import { HistoryPanel, HistoryButton, type Continue } from '../v2/components/HistoryPanel'
import { api } from '../v2/api'
import { useSessionId } from '../v2/hooks/useSessionId'
import '../v2/App.css'
import './aurora.css'

/** "Aurora" interface: the same pages as Classic (versions/v2) in a new shell -- a floating glass side
 * navigation (collapsible; a drawer plus bottom tab bar on phones) and aurora lighting. aurora.css restyles
 * the shared pages through the design tokens, scoped to html[data-ui='aurora'] so Classic never changes. */
type Item = { id: string; label: string; icon: typeof Compass; hint: string }
const GROUPS: { label: string; items: Item[] }[] = [
  { label: 'Discover', items: [
    { id: 'markets', label: 'Markets', icon: LineChart, hint: 'Indices, sectors and movers' },
    { id: 'explore', label: 'Explore', icon: Compass, hint: 'Any stock, fund, ETF or coin' },
  ] },
  { label: 'Ask ARIA', items: [
    { id: 'chat', label: 'Chat', icon: MessageCircle, hint: 'Chat, voice and live avatar' },
    { id: 'research', label: 'Reports', icon: FileText, hint: 'Equity research reports' },
    { id: 'intelligence', label: 'Intelligence', icon: Activity, hint: 'One score per company' },
  ] },
  { label: 'You', items: [
    { id: 'profile', label: 'Profile', icon: User, hint: 'Your money, in one place' },
    { id: 'progress', label: 'Progress', icon: TrendingUp, hint: 'Concepts you have mastered' },
  ] },
]
const FOOT: Item[] = [
  { id: 'feedback', label: 'Feedback', icon: MessageSquareHeart, hint: 'Tell us what to improve' },
  { id: 'settings', label: 'Settings', icon: Settings, hint: 'Look, account and data' },
]
const ALL = [...GROUPS.flatMap((g) => g.items.map((i) => ({ ...i, group: g.label }))), ...FOOT.map((i) => ({ ...i, group: 'ARIA' }))]
const MOBILE_BAR = ['markets', 'explore', 'chat', 'research']
const HOME = 'markets'
const EXTRA_ROUTES = ['disclaimers']

const tabFromHash = () => {
  const id = window.location.hash.replace(/^#\/?/, '')
  return ALL.some((t) => t.id === id) || EXTRA_ROUTES.includes(id) ? id : HOME
}

/** Same URL/history behaviour as Classic: the tab lives in #/id, so Back/Forward and reloads work. */
function useTab(): [string, (id: string) => void, number, string | null] {
  const [tab, setTabState] = useState(tabFromHash)
  const [idx, setIdx] = useState(() => (window.history.state?.idx as number | undefined) ?? 0)
  const [prev, setPrev] = useState<string | null>(null)
  useEffect(() => {
    if (window.history.state?.idx === undefined) window.history.replaceState({ idx: 0, tab: tabFromHash() }, '', `#/${tabFromHash()}`)
    const onPop = (e: PopStateEvent) => {
      setTabState(tabFromHash())
      setIdx((e.state?.idx as number | undefined) ?? 0)
      setPrev((e.state?.from as string | undefined) ?? null)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const go = useCallback((id: string) => {
    if (id === tab) return
    const next = idx + 1
    window.history.pushState({ idx: next, tab: id, from: tab }, '', `#/${id}`)
    setTabState(id); setIdx(next); setPrev(tab)
  }, [tab, idx])
  return [tab, go, idx, prev]
}

/** Card spotlight: the hovered card gets the pointer position as --px/--py (aurora.css paints a soft glow there). */
const SURFACES = '.card, .mk-card, .ri-card, .fb-card, .template-card'
function spotlight(e: React.PointerEvent) {
  const el = (e.target as HTMLElement).closest<HTMLElement>(SURFACES)
  if (!el) return
  const r = el.getBoundingClientRect()
  el.style.setProperty('--px', `${e.clientX - r.left}px`); el.style.setProperty('--py', `${e.clientY - r.top}px`)
}

const readCollapsed = () => { try { return localStorage.getItem('aria_ux3_collapsed') === '1' } catch { return false } }

export default function App() {
  const [sessionId, resetSession, selectSession, restored] = useSessionId()
  const [tab, go, idx, prev] = useTab()
  const [continueAs, setContinueAs] = useState<Continue | null>(null)
  const [pendingAsk, setPendingAsk] = useState<string | null>(null)
  const [instrumentId, setInstrumentId] = useState<string | null>(null)
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(readCollapsed)
  const [drawer, setDrawer] = useState(false)

  const page = tab === 'disclaimers' ? { label: 'Disclaimers', group: 'ARIA', hint: 'What ARIA is and is not' } : ALL.find((t) => t.id === tab)!
  const prevLabel = ALL.find((t) => t.id === prev)?.label
  useEffect(() => { document.title = `${page.label} - ARIA` }, [page.label])
  useEffect(() => { document.documentElement.classList.toggle('ux3-collapsed', collapsed) }, [collapsed])
  useEffect(() => {
    if (restored) return
    api.listConversations('', false, 0, 1).then((p) => { if (p.items[0]) selectSession(p.items[0].id) }).catch(() => {})
  }, [restored, selectSession])

  const open = (id: string) => { setDrawer(false); go(id) }
  const askInChat = (q: string) => { setPendingAsk(q); open('chat') }
  const newSession = () => { resetSession(); open('chat') }
  const toggleCollapsed = () => setCollapsed((c) => { try { localStorage.setItem('aria_ux3_collapsed', c ? '0' : '1') } catch { /* not saved */ } return !c })

  const navItem = ({ id, label, icon: Icon }: Item) => (
    <button key={id} type="button" className={`ux3-item${tab === id ? ' is-active' : ''}`} aria-current={tab === id ? 'page' : undefined}
      onClick={() => open(id)} title={collapsed ? label : undefined}>
      <span className="ux3-item-ico"><Icon size={18} aria-hidden="true" /></span>
      <span className="ux3-item-label">{label}</span>
    </button>
  )

  return (
    <div className="ux3">
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>Skip to main content</a>
      <div className="ux3-sky" aria-hidden="true"><i /><i /><i /></div>

      <aside className={`ux3-side${drawer ? ' is-open' : ''}`} aria-label="Main navigation">
        <div className="ux3-brand">
          <button type="button" className="ux3-logo" onClick={() => open(HOME)} aria-label="ARIA home">
            {collapsed ? <BrandMark /> : <BrandLogo />}
          </button>
          <button type="button" className="ux3-icon-btn ux3-collapse" onClick={toggleCollapsed} aria-label={collapsed ? 'Expand navigation' : 'Collapse navigation'} aria-pressed={collapsed}>
            <ChevronsLeft size={18} aria-hidden="true" />
          </button>
          <button type="button" className="ux3-icon-btn ux3-close" onClick={() => setDrawer(false)} aria-label="Close menu"><X size={18} aria-hidden="true" /></button>
        </div>
        <button type="button" className="ux3-new" onClick={newSession} title={collapsed ? 'New chat' : undefined}>
          <Plus size={18} aria-hidden="true" /><span>New chat</span>
        </button>
        <nav className="ux3-nav">
          {GROUPS.map((g) => <div key={g.label} className="ux3-group">
            <p className="ux3-group-label">{g.label}</p>
            {g.items.map(navItem)}
          </div>)}
        </nav>
        <div className="ux3-foot">
          {FOOT.map(navItem)}
          <p className="ux3-note">Educational only. Not investment advice. <a href="#/disclaimers" onClick={(e) => { e.preventDefault(); open('disclaimers') }}>Disclaimers</a></p>
        </div>
      </aside>
      {drawer && <button type="button" className="ux3-scrim" aria-label="Close menu" onClick={() => setDrawer(false)} />}

      <div className="ux3-body">
        <DisclaimerStrip onOpen={() => open('disclaimers')} />
        <header className="ux3-top">
          <button type="button" className="ux3-icon-btn ux3-menu" onClick={() => setDrawer(true)} aria-label="Open menu"><Menu size={20} aria-hidden="true" /></button>
          {tab !== HOME && idx > 0 && prevLabel && (
            <button type="button" className="ux3-icon-btn" onClick={() => window.history.back()} aria-label={`Back to ${prevLabel}`} title={`Back to ${prevLabel}`}>
              <ArrowLeft size={18} aria-hidden="true" />
            </button>
          )}
          <div className="ux3-crumb">
            <span>{page.group}</span>
            <b>{page.label}</b>
          </div>
          <div className="ux3-top-tools">
            <GlobalSearch label="Search stocks, funds, ETFs…" onOpenInstrument={setInstrumentId} onBrowse={() => open('explore')} />
            {tab === 'chat' && <HistoryButton />}
            <ModeToggle />
          </div>
        </header>
        {(tab === 'markets' || tab === 'explore') && <TickerTape onOpen={(s) => { setSelectedSymbol(s); open('markets') }} />}
        {tab === 'chat' && <HistoryPanel activeId={sessionId} onContinue={(id, mode) => { selectSession(id); setContinueAs((c) => ({ mode, n: (c?.n ?? 0) + 1 })); open('chat') }} onActiveGone={newSession} />}

        <main className={`ux3-main ux3-page-${tab}`} id="main" tabIndex={-1} key={tab} onPointerMove={spotlight}>
          {tab === 'chat' && <ChatTab sessionId={sessionId} continueAs={continueAs} onOpenProfile={() => open('profile')} pendingAsk={pendingAsk} onAskHandled={() => setPendingAsk(null)} />}
          {tab === 'markets' && <MarketsTab onAsk={askInChat} onOpenStock={setSelectedSymbol} selectedSymbol={selectedSymbol} />}
          {tab === 'explore' && <ExploreTab onOpenInstrument={setInstrumentId} />}
          {tab === 'disclaimers' && <DisclaimersPage />}
          {tab === 'feedback' && <FeedbackTab />}
          {tab === 'research' && <ResearchTab onAsk={askInChat} />}
          {tab === 'intelligence' && <IntelligenceTab />}
          {tab === 'profile' && <div className="page-wrap"><ProfileTab onAskInChat={askInChat} /></div>}
          {tab === 'progress' && <div className="page-wrap"><ProgressTab sessionId={sessionId} onOpenChat={() => open('chat')} /></div>}
          {tab === 'settings' && <div className="page-wrap"><SettingsTab theme="vitara-markets" /></div>}
        </main>
      </div>

      <nav className="ux3-tabbar" aria-label="Quick navigation">
        {MOBILE_BAR.map((id) => { const t = ALL.find((x) => x.id === id)!; return (
          <button key={id} type="button" className={tab === id ? 'is-active' : ''} aria-current={tab === id ? 'page' : undefined} onClick={() => open(id)}>
            <t.icon size={20} aria-hidden="true" /><span>{t.label}</span>
          </button>) })}
        <button type="button" onClick={() => setDrawer(true)}><Menu size={20} aria-hidden="true" /><span>More</span></button>
      </nav>

      <InstrumentDrawer id={instrumentId} sessionId={sessionId} onClose={() => setInstrumentId(null)} onDisclaimers={() => open('disclaimers')} />
    </div>
  )
}
