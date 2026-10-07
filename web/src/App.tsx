import { useCallback, useEffect, useState } from 'react'
import { ArrowLeft } from 'lucide-react'
import { Sidebar, SIDEBAR_TABS } from './components/Sidebar'
import { ChatTab } from './components/chat/ChatTab'
import { ProfileTab } from './components/profile/ProfileTab'
import { ResearchTab } from './components/research/ResearchTab'
import { IntelligenceTab } from './components/research/IntelligenceTab'
import { ProgressTab } from './components/progress/ProgressTab'
import { SettingsTab } from './components/settings/SettingsTab'
import { useSessionId } from './hooks/useSessionId'
import './App.css'

const TAB_IDS = SIDEBAR_TABS.map((t) => t.id)
const tabFromHash = () => {
  const id = window.location.hash.replace(/^#\/?/, '')
  return TAB_IDS.includes(id) ? id : 'chat'
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
  const prevLabel = SIDEBAR_TABS.find((t) => t.id === prev)?.label

  function newSession() {
    resetSession()
    setTab('chat')
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to main content</a>
      <Sidebar tabs={SIDEBAR_TABS} active={tab} onChange={setTab} onNewSession={newSession} />
      <main className="app-main" id="main" tabIndex={-1}>
        {tab !== 'chat' && idx > 0 && prevLabel && (
          <button type="button" className="back-bar" onClick={() => window.history.back()}>
            <ArrowLeft size={15} aria-hidden="true" /> Back to {prevLabel}
          </button>
        )}
        {tab === 'chat' && <ChatTab sessionId={sessionId} onOpenProfile={() => setTab('profile')} />}
        {tab === 'research' && <ResearchTab />}
        {tab === 'intelligence' && <IntelligenceTab />}
        {tab === 'profile' && (
          <div className="page-wrap">
            <ProfileTab />
          </div>
        )}
        {tab === 'progress' && (
          <div className="page-wrap">
            <ProgressTab sessionId={sessionId} onOpenChat={() => setTab('chat')} />
          </div>
        )}
        {tab === 'settings' && (
          <div className="page-wrap">
            <SettingsTab />
          </div>
        )}
      </main>
    </div>
  )
}
