import { useState } from 'react'
import { Sidebar, SIDEBAR_TABS } from './components/Sidebar'
import { ChatTab } from './components/chat/ChatTab'
import { ProfileTab } from './components/profile/ProfileTab'
import { ProgressTab } from './components/progress/ProgressTab'
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
      <Sidebar tabs={SIDEBAR_TABS} active={tab} onChange={setTab} onNewSession={newSession} />
      <main className="app-main">
        {tab === 'chat' && <ChatTab sessionId={sessionId} />}
        {tab === 'profile' && (
          <div className="page-wrap">
            <ProfileTab sessionId={sessionId} />
          </div>
        )}
        {tab === 'progress' && (
          <div className="page-wrap">
            <ProgressTab sessionId={sessionId} />
          </div>
        )}
      </main>
    </div>
  )
}
