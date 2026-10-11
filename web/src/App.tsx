import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Sidebar, SIDEBAR_TABS, MARKETS_TAB } from './components/Sidebar'
import { ChatTab } from './components/chat/ChatTab'
import { ProfileTab } from './components/profile/ProfileTab'
import { ResearchTab } from './components/research/ResearchTab'
import { IntelligenceTab } from './components/research/IntelligenceTab'
import { ProgressTab } from './components/progress/ProgressTab'
import { SettingsTab } from './components/settings/SettingsTab'
import { MarketsTab } from './components/markets/MarketsTab'
import { TickerTape } from './components/markets/TickerTape'
import { useSessionId } from './hooks/useSessionId'
import { getTheme, setTheme, type ThemeId } from './theme'
import './App.css'

const tabsFor = (theme: ThemeId) => (theme === 'vitara-markets' ? [MARKETS_TAB, ...SIDEBAR_TABS] : SIDEBAR_TABS)
const defaultTab = (theme: ThemeId) => (theme === 'vitara-markets' ? 'markets' : 'chat')
const tabFromHash = () => {
  const id = window.location.hash.replace(/^#\/?/, '')
  const theme = getTheme()
  return tabsFor(theme).some((t) => t.id === id) ? id : defaultTab(theme)
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
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null) // opened from the ticker tape, shown by the Markets tab drawer
  const tabs = tabsFor(theme)
  const prevLabel = tabs.find((t) => t.id === prev)?.label
  const askInChat = (q: string) => { setPendingAsk(q); setTab('chat') }

  function newSession() {
    resetSession()
    setTab('chat')
  }
  function changeTheme(id: ThemeId) {
    setTheme(id)
    setThemeState(id)
    if (!tabsFor(id).some((t) => t.id === tab)) setTab(defaultTab(id))
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to main content</a>
      <Sidebar tabs={tabs} active={tab} onChange={setTab} onNewSession={newSession} />
      {theme === 'vitara-markets' && <TickerTape onOpen={(s) => { setSelectedSymbol(s); setTab('markets') }} />}
      <main className="app-main" id="main" tabIndex={-1}>
        {tab !== defaultTab(theme) && idx > 0 && prevLabel && (
          <button type="button" className="back-bar" onClick={() => window.history.back()}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to {prevLabel}
          </button>
        )}
        {tab === 'chat' && <ChatTab sessionId={sessionId} onOpenProfile={() => setTab('profile')} pendingAsk={pendingAsk} onAskHandled={() => setPendingAsk(null)} />}
        {tab === 'markets' && <MarketsTab onAsk={askInChat} onOpenStock={setSelectedSymbol} selectedSymbol={selectedSymbol} />}
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
    </div>
  )
}
