import { useState } from 'react'
import { Sidebar, SIDEBAR_TABS } from './components/Sidebar'
import { ChatTab } from './components/chat/ChatTab'
import { ProfileTab } from './components/profile/ProfileTab'
import { ResearchTab } from './components/research/ResearchTab'
import { IntelligenceTab } from './components/research/IntelligenceTab'
import { ProgressTab } from './components/progress/ProgressTab'
import { SettingsTab } from './components/settings/SettingsTab'
import { useSessionId } from './hooks/useSessionId'
import './App.css'

export default function App() {
  const [sessionId, resetSession] = useSessionId()
  const [tab, setTab] = useState('chat')

  function newSession() {
    resetSession()
    setTab('chat')
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">Skip to main content</a>
      <Sidebar tabs={SIDEBAR_TABS} active={tab} onChange={setTab} onNewSession={newSession} />
      <main className="app-main" id="main" tabIndex={-1}>
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
