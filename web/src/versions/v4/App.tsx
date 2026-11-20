import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Activity, ArrowLeft, ChevronDown, Compass, FileText, LineChart, Menu, MessageCircle, MessageSquareHeart, Plus, Settings,
  TrendingUp, User, X,
} from 'lucide-react'
import { BrandLogo } from '../../components/brand/BrandLogo'
import { ChatTab } from '../v2/components/chat/ChatTab'
import { ProfileTab } from '../v2/components/profile/ProfileTab'
import { ResearchTab } from '../v2/components/research/ResearchTab'
import { IntelligenceTab } from '../v2/components/research/IntelligenceTab'
import { ProgressTab } from '../v2/components/progress/ProgressTab'
import { SettingsTab } from '../v2/components/settings/SettingsTab'
import { FeedbackTab } from '../../components/feedback/FeedbackTab'
import { ModeToggle } from '../v2/components/ModeToggle'
import { MarketsTab } from '../v2/components/markets/MarketsTab'
import { ExploreTab } from '../v2/components/explore/ExploreTab'
import { GlobalSearch } from '../v2/components/explore/GlobalSearch'
import { InstrumentDrawer } from '../v2/components/explore/InstrumentDrawer'
import { DisclaimerStrip } from '../v2/components/disclaimer/DisclaimerStrip'
import { DisclaimersPage } from '../v2/components/disclaimer/DisclaimersPage'
import { HistoryPanel, HistoryButton, type Continue } from '../v2/components/HistoryPanel'
import { useMarket } from '../v2/hooks/useMarket'
import type { Overview } from '../v2/components/markets/types'
import { api } from '../v2/api'
import { useSessionId } from '../v2/hooks/useSessionId'
import { LiveRibbon, MoodChip } from './Live'
import { useNumberFlash } from './useNumberFlash'
import { LiveDeck } from './LiveDeck'
import { useDepth, useMagnets, useScrollReveal } from './motion'
import '../v2/App.css'
import '../v3/aurora.css' // shared palette + page polish (scoped to Aurora and Pulse)
import './pulse.css'

/** "Pulse" interface: the same pages as Classic in a top-navigation shell with live market effects --
 * a calm backdrop that tints with market mood, a live index ribbon, a market-mood gauge, flashing prices, a live Markets
 * dashboard (LiveDeck), card depth, magnetic buttons, scroll reveal and a blur-focus page transition. pulse.css is scoped to html[data-ui='pulse']. */
type Item = { id: string; label: string; icon: typeof Compass }
const MAIN: Item[] = [
  { id: 'markets', label: 'Markets', icon: LineChart },
  { id: 'explore', label: 'Explore', icon: Compass },
  { id: 'chat', label: 'Chat', icon: MessageCircle },
  { id: 'research', label: 'Reports', icon: FileText },
  { id: 'intelligence', label: 'Intelligence', icon: Activity },
]
const YOU: Item[] = [
  { id: 'profile', label: 'Profile', icon: User },
  { id: 'progress', label: 'Progress', icon: TrendingUp },
  { id: 'feedback', label: 'Feedback', icon: MessageSquareHeart },
  { id: 'settings', label: 'Settings', icon: Settings },
]
const ALL = [...MAIN, ...YOU]
const HOME = 'markets'
const EXTRA_ROUTES = ['disclaimers']
const tabFromHash = () => {
  const id = window.location.hash.replace(/^#\/?/, '')
  return ALL.some((t) => t.id === id) || EXTRA_ROUTES.includes(id) ? id : HOME
}

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

export default function App() {
  const [sessionId, resetSession, selectSession, restored] = useSessionId()
  const [tab, go, idx, prev] = useTab()
  const [continueAs, setContinueAs] = useState<Continue | null>(null)
  const [pendingAsk, setPendingAsk] = useState<string | null>(null)
  const [instrumentId, setInstrumentId] = useState<string | null>(null)
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const nav = useRef<HTMLElement>(null)
  const root = useRef<HTMLDivElement>(null)
  useNumberFlash(root)
  useDepth(root) // on the stable root: <main> remounts on every page change
  useMagnets()
  useScrollReveal(root, tab)

  const ov = useMarket<Overview>('/api/markets/overview', 30_000)
  const india = ov.data?.items.filter((i) => i.group === 'india') ?? []
  const ribbon = [...india, ...(ov.data?.items.filter((i) => i.group !== 'india') ?? [])].slice(0, 14)
  const mood = india.length ? (india.filter((i) => i.change_pct > 0).length / india.length) * 2 - 1 : 0

  const page = tab === 'disclaimers' ? 'Disclaimers' : ALL.find((t) => t.id === tab)!.label
  const prevLabel = ALL.find((t) => t.id === prev)?.label
  useEffect(() => { document.title = `${page} - ARIA` }, [page])
  useEffect(() => {
    if (restored) return
    api.listConversations('', false, 0, 1).then((p) => { if (p.items[0]) selectSession(p.items[0].id) }).catch(() => {})
  }, [restored, selectSession])

  // The glowing pill under the nav links: sits on the active link, follows the pointer while hovering.
  const pillTo = useCallback((el: Element | null | undefined) => {
    const n = nav.current
    if (!n || !(el instanceof HTMLElement)) { n?.style.setProperty('--pill-o', '0'); return }
    n.style.setProperty('--pill-x', `${el.offsetLeft}px`); n.style.setProperty('--pill-w', `${el.offsetWidth}px`); n.style.setProperty('--pill-o', '1')
  }, [])
  const pillHome = useCallback(() => pillTo(nav.current?.querySelector('.is-active')), [pillTo])
  useEffect(() => {
    pillHome()
    const ro = new ResizeObserver(pillHome)
    if (nav.current) ro.observe(nav.current)
    return () => ro.disconnect()
  }, [tab, pillHome])

  const hide = (id: string) => (document.getElementById(id) as HTMLElement & { hidePopover?: () => void } | null)?.hidePopover?.()
  const open = (id: string) => { hide('ux4-you'); hide('ux4-menu'); go(id) }
  const askInChat = (q: string) => { setPendingAsk(q); open('chat') }
  const newSession = () => { resetSession(); open('chat') }
  const youActive = YOU.some((y) => y.id === tab)

  return (
    <div className="ux4" ref={root}>
      <a className="skip-link" href="#main" onClick={(e) => { e.preventDefault(); document.getElementById('main')?.focus() }}>Skip to main content</a>
      <div className="ux4-glow" aria-hidden="true" data-mood={mood > 0.2 ? 'up' : mood < -0.2 ? 'down' : 'flat'} />
      <DisclaimerStrip onOpen={() => open('disclaimers')} />

      <header className="ux4-bar">
        <button type="button" className="ux4-logo" onClick={() => open(HOME)} aria-label="ARIA home"><BrandLogo /></button>
        <nav ref={nav} className="ux4-nav" aria-label="Main" onPointerLeave={pillHome}>
          <span className="ux4-pill" aria-hidden="true" />
          {MAIN.map(({ id, label, icon: Icon }) => (
            <button key={id} type="button" className={`ux4-link${tab === id ? ' is-active' : ''}`} aria-current={tab === id ? 'page' : undefined}
              onClick={() => open(id)} onPointerEnter={(e) => pillTo(e.currentTarget)} onFocus={(e) => pillTo(e.currentTarget)} title={label}>
              <Icon size={17} aria-hidden="true" /><span>{label}</span>
            </button>
          ))}
          <button type="button" className={`ux4-link${youActive ? ' is-active' : ''}`} popoverTarget="ux4-you" onPointerEnter={(e) => pillTo(e.currentTarget)} onFocus={(e) => pillTo(e.currentTarget)} title="You">
            <User size={17} aria-hidden="true" /><span>{youActive ? page : 'You'}</span><ChevronDown size={14} aria-hidden="true" />
          </button>
        </nav>
        <div id="ux4-you" popover="auto" className="ux4-pop">
          {YOU.map(({ id, label, icon: Icon }) => (
            <button key={id} type="button" className={tab === id ? 'is-active' : ''} onClick={() => open(id)}><Icon size={17} aria-hidden="true" />{label}</button>
          ))}
        </div>
        <div className="ux4-tools">
          <MoodChip items={india} open={ov.data ? ov.data.status.open : null} label={ov.data?.status.label ?? ''} />
          <GlobalSearch label="Search" onOpenInstrument={setInstrumentId} onBrowse={() => open('explore')} />
          {tab === 'chat' && <HistoryButton />}
          <ModeToggle />
          <button type="button" className="ux4-new" onClick={newSession}><Plus size={17} aria-hidden="true" /><span>New chat</span></button>
          <button type="button" className="ux4-burger" popoverTarget="ux4-menu" aria-label="Open menu"><Menu size={20} aria-hidden="true" /></button>
        </div>
      </header>
      <div id="ux4-menu" popover="auto" className="ux4-menu">
        <button type="button" className="ux4-menu-close" popoverTarget="ux4-menu" popoverTargetAction="hide" aria-label="Close menu"><X size={22} aria-hidden="true" /></button>
        <BrandLogo />
        <div className="ux4-menu-list">
          {ALL.map(({ id, label, icon: Icon }, i) => (
            <button key={id} type="button" className={tab === id ? 'is-active' : ''} onClick={() => open(id)} style={{ animationDelay: `${i * 40}ms` }}>
              <Icon size={22} aria-hidden="true" />{label}
            </button>
          ))}
        </div>
        <button type="button" className="ux4-new" onClick={newSession}><Plus size={17} aria-hidden="true" /><span>New chat</span></button>
      </div>

      <LiveRibbon items={ribbon} onOpen={(s) => { setSelectedSymbol(s); open('markets') }} />
      {tab === 'chat' && <HistoryPanel activeId={sessionId} onContinue={(id, mode) => { selectSession(id); setContinueAs((c) => ({ mode, n: (c?.n ?? 0) + 1 })); open('chat') }} onActiveGone={newSession} />}

      <main className={`ux3-main ux4-main ux3-page-${tab}`} id="main" tabIndex={-1} key={tab}>
        {tab !== HOME && idx > 0 && prevLabel && (
          <button type="button" className="ux4-back" onClick={() => window.history.back()}><ArrowLeft size={15} aria-hidden="true" /> Back to {prevLabel}</button>
        )}
        {tab === 'chat' && <ChatTab sessionId={sessionId} continueAs={continueAs} onOpenProfile={() => open('profile')} pendingAsk={pendingAsk} onAskHandled={() => setPendingAsk(null)} />}
        {tab === 'markets' && <><LiveDeck onDetails={setSelectedSymbol} /><MarketsTab onAsk={askInChat} onOpenStock={setSelectedSymbol} selectedSymbol={selectedSymbol} /></>}
        {tab === 'explore' && <ExploreTab onOpenInstrument={setInstrumentId} />}
        {tab === 'disclaimers' && <DisclaimersPage />}
        {tab === 'feedback' && <FeedbackTab />}
        {tab === 'research' && <ResearchTab onAsk={askInChat} />}
        {tab === 'intelligence' && <IntelligenceTab />}
        {tab === 'profile' && <div className="page-wrap"><ProfileTab onAskInChat={askInChat} /></div>}
        {tab === 'progress' && <div className="page-wrap"><ProgressTab sessionId={sessionId} onOpenChat={() => open('chat')} /></div>}
        {tab === 'settings' && <div className="page-wrap"><SettingsTab theme="vitara-markets" /></div>}
      </main>

      <InstrumentDrawer id={instrumentId} sessionId={sessionId} onClose={() => setInstrumentId(null)} onDisclaimers={() => open('disclaimers')} />
    </div>
  )
}
