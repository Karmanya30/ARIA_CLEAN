import { Sparkles, MessageCircle, User, TrendingUp, Plus, FileText, Activity, Settings } from 'lucide-react'
import './Sidebar.css'

export interface NavDef {
  id: string
  label: string
  icon: React.ReactNode
}

/** Persistent left nav, replacing the old top Header+Tabs bar. Deliberately
 * doesn't clone a multi-conversation "chat history" list or a fake user/
 * plan card the way some AI-chat-app references do -- ARIA has no accounts
 * and no persisted list of past sessions to switch between, so faking
 * either would be decoration that doesn't do anything. "New session" is
 * the honest equivalent: it's a real, working reset. */
export function Sidebar({
  tabs,
  active,
  onChange,
  onNewSession,
}: {
  tabs: NavDef[]
  active: string
  onChange: (id: string) => void
  onNewSession: () => void
}) {
  return (
    <aside className="app-sidebar">
      <div className="sidebar-brand">
        <span className="app-mark">
          <Sparkles size={16} />
        </span>
        <span className="app-name">ARIA</span>
      </div>

      <button className="sidebar-new-btn" onClick={onNewSession} type="button">
        <Plus size={15} />
        New session
      </button>

      <nav className="sidebar-nav" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            role="tab"
            aria-selected={active === tab.id}
            aria-current={active === tab.id ? 'page' : undefined}
            className={active === tab.id ? 'sidebar-nav-item active' : 'sidebar-nav-item'}
            onClick={() => onChange(tab.id)}
            type="button"
          >
            {tab.icon}
            <span className="sidebar-nav-label">{tab.label}</span>
          </button>
        ))}
      </nav>

      <div className="sidebar-footer">
        <p className="sidebar-tagline">
          Personal finance &middot; tutor &middot; market &amp; equity research — one Indian AI
          assistant.
        </p>
      </div>
    </aside>
  )
}

export const SIDEBAR_TABS: NavDef[] = [
  { id: 'chat', label: 'Chat', icon: <MessageCircle size={16} /> },
  { id: 'research', label: 'Research reports', icon: <FileText size={16} /> },
  { id: 'intelligence', label: 'Company intelligence', icon: <Activity size={16} /> },
  { id: 'profile', label: 'Your Profile', icon: <User size={16} /> },
  { id: 'progress', label: 'Your Progress', icon: <TrendingUp size={16} /> },
  { id: 'settings', label: 'Settings', icon: <Settings size={16} /> },
]
