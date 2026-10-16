import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Sidebar, SIDEBAR_TABS, MARKETS_TAB, EXPLORE_TAB } from './components/Sidebar'
import { ChatTab } from './components/chat/ChatTab'
import { ProfileTab } from './components/profile/ProfileTab'
import { ResearchTab } from './components/research/ResearchTab'
import { IntelligenceTab } from './components/research/IntelligenceTab'
import { ProgressTab } from './components/progress/ProgressTab'
import { SettingsTab } from './components/settings/SettingsTab'
import { ModeToggle } from './components/ModeToggle'
import { MarketsTab } from './components/markets/MarketsTab'
import { TickerTape } from './components/markets/TickerTape'
import { ExploreTab } from './components/explore/ExploreTab'
import { GlobalSearch } from './components/explore/GlobalSearch'
import { InstrumentDrawer } from './components/explore/InstrumentDrawer'
import { DisclaimerStrip } from './components/disclaimer/DisclaimerStrip'
import { DisclaimersPage } from './components/disclaimer/DisclaimersPage'
import { useSessionId } from './hooks/useSessionId'
import { getTheme, hasMarkets, setTheme, type ThemeId } from './theme'
import './App.css'

const tabsFor = (theme: ThemeId) =>
  hasMarkets(theme) ? [MARKETS_TAB, EXPLORE_TAB, ...SIDEBAR_TABS] : [SIDEBAR_TABS[0], EXPLORE_TAB, ...SIDEBAR_TABS.slice(1)]
const defaultTab = (theme: ThemeId) => (theme === 'vitara-markets' ? 'markets' : 'chat')
/** Pages that are reachable by link (#/disclaimers) but are not in the navigation. */
const SHORT_LABEL: Record<string, string> = { research: 'Reports', intelligence: 'Intelligence', profile: 'Profile', progress: 'Progress' }
const EXTRA_ROUTES = ['disclaimers']
const tabFromHash = () => {
  const id = window.location.hash.replace(/^#\/?/, '')
  const theme = getTheme()
  return tabsFor(theme).some((t) => t.id === id) || EXTRA_ROUTES.includes(id) ? id : defaultTab(theme)
}

/** The open tab lives in the URL (#/profile) and in browser history, so the browser's Back/Forward buttons and a phone's back
 * gesture move between tabs, and a page can be linked or reloaded. `idx` counts in-app entries so we know when Back has somewhere to go. */
function useTab(): [string, (id: string) => void, number, string | null] {
  const [tab, setTabState] = useState(tabFromHash)
  const [idx, setIdx] = useState(() => (window.history.state?.idx as number | undefined) ?? 0)
  const [prev, setPrev] = useState<string | null>(null)
  useEffect(() => {
    if (window.history.state?.idx === undefined) window.history.replaceState({ idx: 0, tab: tabFromHash() }, '')
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
  const [sessionId, resetSession] = useSessionId()
  const [tab, setTab, idx, prev] = useTab()
  const [pendingAsk, setPendingAsk] = useState<string | null>(null)
  const [theme, setThemeState] = useState<ThemeId>(getTheme)
  const [instrumentId, setInstrumentId] = useState<string | null>(null) // any instrument opened from search / Explore, shown in its drawer
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null) // opened from the ticker tape, shown by the Markets tab drawer
  // Vitara Clear uses shorter tab names so the whole bar fits at laptop widths
  const tabs = tabsFor(theme).map((t) => (theme === 'vitara-clear' && SHORT_LABEL[t.id] ? { ...t, label: SHORT_LABEL[t.id] } : t))
  const prevLabel = tabs.find((t) => t.id === prev)?.label
  const askInChat = (q: string) => { setPendingAsk(q); setTab('chat') }

  function newSession() {
    resetSession()
    setTab('chat')
  }
  function changeTheme(id: ThemeId) {
    setTheme(id)
    setThemeState(id)
    if (!tabsFor(id).some((t) => t.id === tab) && !EXTRA_ROUTES.includes(tab)) setTab(defaultTab(id))
  }

  return (
    <>
    <DisclaimerStrip onOpen={() => setTab('disclaimers')} />
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to main content</a>
      <Sidebar
        tabs={tabs}
        active={tab}
        onChange={setTab}
        onNewSession={newSession}
        newLabel={theme === 'vitara-clear' ? 'New chat' : 'New session'}
        search={<GlobalSearch label={theme === 'vitara-clear' ? 'Search anything' : 'Search'} onOpenInstrument={setInstrumentId} onBrowse={() => setTab('explore')} />}
        extra={hasMarkets(theme) ? <ModeToggle /> : undefined}
      />
      {theme === 'vitara-markets' && <TickerTape onOpen={(s) => { setSelectedSymbol(s); setTab('markets') }} />}
      <main className="app-main" id="main" tabIndex={-1}>
        {tab !== defaultTab(theme) && idx > 0 && prevLabel && (
          <button type="button" className="back-bar" onClick={() => window.history.back()}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to {prevLabel}
          </button>
        )}
        {tab === 'chat' && <ChatTab sessionId={sessionId} onOpenProfile={() => setTab('profile')} pendingAsk={pendingAsk} onAskHandled={() => setPendingAsk(null)} />}
        {tab === 'markets' && <MarketsTab onAsk={askInChat} onOpenStock={setSelectedSymbol} selectedSymbol={selectedSymbol} />}
        {tab === 'explore' && <ExploreTab onOpenInstrument={setInstrumentId} />}
        {tab === 'disclaimers' && <DisclaimersPage />}
        {tab === 'research' && <ResearchTab />}
        {tab === 'intelligence' && <IntelligenceTab />}
        {tab === 'profile' && (
          <div className="page-wrap">
            <ProfileTab onAskInChat={askInChat} />
          </div>
        )}
        {tab === 'progress' && (
          <div className="page-wrap">
            <ProgressTab sessionId={sessionId} onOpenChat={() => setTab('chat')} />
          </div>
        )}
        {tab === 'settings' && (
          <div className="page-wrap">
            <SettingsTab theme={theme} onTheme={changeTheme} />
          </div>
        )}
      </main>
      <InstrumentDrawer id={instrumentId} sessionId={sessionId} onClose={() => setInstrumentId(null)} onDisclaimers={() => setTab('disclaimers')} />
    </div>
    </>
  )
}
