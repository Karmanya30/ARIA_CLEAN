import { useCallback, useEffect, useRef, useState } from 'react'
import { Archive, ArchiveRestore, ChevronDown, Download, History, Pencil, Pin, PinOff, Search, Trash2 } from 'lucide-react'
import { api, CHAT_SAVED, type ConversationSummary } from '../api'
import './ConversationList.css'

const DAY = 86_400_000

/** Pinned first, then by how long ago the chat was last used. */
export function groupOf(c: ConversationSummary, now = Date.now()): string {
  if (c.pinned) return 'Pinned'
  const d = new Date(c.updated_at || c.created_at)
  const startOfToday = new Date(now).setHours(0, 0, 0, 0)
  const t = d.getTime()
  if (t >= startOfToday) return 'Today'
  if (t >= startOfToday - DAY) return 'Yesterday'
  if (t >= startOfToday - 7 * DAY) return 'Previous 7 days'
  if (t >= startOfToday - 30 * DAY) return 'Previous 30 days'
  return 'Older'
}

export function ConversationList({ activeId, onSelect, onActiveGone }: {
  activeId: string
  onSelect: (id: string) => void
  onActiveGone: () => void // the open chat was deleted or archived
}) {
  const [items, setItems] = useState<ConversationSummary[]>([])
  const [next, setNext] = useState<number | null>(null)
  const [q, setQ] = useState('')
  const [archived, setArchived] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [open, setOpen] = useState(false) // narrow screens only: the list is a drawer under the top bar
  const seq = useRef(0) // a slow earlier response must not overwrite a newer one

  const load = useCallback((query: string, arch: boolean) => {
    const mine = ++seq.current
    setLoading(true)
    api.listConversations(query, arch, 0).then((p) => {
      if (mine !== seq.current) return
      setItems(p.items); setNext(p.next_offset); setError(null)
    }).catch((e) => { if (mine === seq.current) setError(e instanceof Error && e.message !== 'Not Found' ? e.message : 'Chat history is unavailable right now.') })
      .finally(() => { if (mine === seq.current) setLoading(false) })
  }, [])

  // debounced search; also reloads when a question is saved or the chat changes
  useEffect(() => {
    const t = setTimeout(() => load(q, archived), q ? 300 : 0)
    return () => clearTimeout(t)
  }, [q, archived, activeId, load])
  useEffect(() => {
    const on = () => load(q, archived)
    window.addEventListener(CHAT_SAVED, on)
    return () => window.removeEventListener(CHAT_SAVED, on)
  }, [q, archived, load])

  useEffect(() => {
    const again = () => { if (!document.hidden) load(q, archived) }
    const timer = setInterval(again, 20000)
    window.addEventListener('focus', again)
    return () => { clearInterval(timer); window.removeEventListener('focus', again) }
  }, [q, archived, load])

  async function more() {
    if (next === null) return
    const p = await api.listConversations(q, archived, next)
    setItems((cur) => [...cur, ...p.items.filter((i) => !cur.some((c) => c.id === i.id))])
    setNext(p.next_offset)
  }
  async function run(fn: () => Promise<unknown>, id?: string) {
    try {
      await fn()
      if (id && id === activeId) onActiveGone()
      load(q, archived)
    } catch (e) { setError(e instanceof Error ? e.message : 'That did not work') }
  }
  const rename = (c: ConversationSummary) => {
    const title = window.prompt('Rename chat', c.title)?.trim()
    if (title && title !== c.title) void run(() => api.updateConversation(c.id, { title }))
  }
  const remove = (c: ConversationSummary) => {
    if (window.confirm(`Delete “${c.title}”? This cannot be undone.`)) void run(() => api.deleteConversation(c.id), c.id)
  }

  const groups: Record<string, ConversationSummary[]> = {}
  for (const c of items) (groups[groupOf(c)] ??= []).push(c)
  const order = ['Pinned', 'Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days', 'Older']

  return (
    <section className={open ? 'conv-list open' : 'conv-list'} aria-label="Chat history">
      <button type="button" className="conv-toggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <History size={15} aria-hidden="true" /> Chat history <ChevronDown size={14} aria-hidden="true" />
      </button>
      <h2 className="conv-heading">Chats</h2>
      <div className="conv-body">
      <label className="conv-search">
        <Search size={13} aria-hidden="true" />
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search chats" aria-label="Search chats" />
      </label>
      {error && <p className="conv-note" role="alert">{error}</p>}
      {!loading && !error && items.length === 0 && (
        <p className="conv-note">{q ? 'No chats match your search.' : archived ? 'No archived chats.' : 'No chats yet. Anything you ask in chat, voice or the live meeting is saved here.'}</p>
      )}
      {order.filter((g) => groups[g]).map((g) => (
        <div key={g} className="conv-group">
          <h3>{g}</h3>
          <ul>
            {groups[g].map((c) => (
              <li key={c.id} className={c.id === activeId ? 'conv-item active' : 'conv-item'}>
                <button type="button" className="conv-open" onClick={() => onSelect(c.id)} title={c.title}>
                  <span className="conv-title">{c.title}</span>
                  {c.snippet && <span className="conv-snippet">{c.snippet}</span>}
                </button>
                <span className="conv-actions">
                  {!archived && (
                    <button type="button" aria-label={c.pinned ? 'Unpin' : 'Pin'} title={c.pinned ? 'Unpin' : 'Pin'}
                      onClick={() => run(() => api.updateConversation(c.id, { pinned: !c.pinned }))}>
                      {c.pinned ? <PinOff size={13} /> : <Pin size={13} />}
                    </button>
                  )}
                  <button type="button" aria-label="Rename" title="Rename" onClick={() => rename(c)}><Pencil size={13} /></button>
                  <a aria-label="Export as Markdown" title="Export as Markdown" href={api.conversationExportUrl(c.id, 'markdown')} download><Download size={13} /></a>
                  <button type="button" aria-label={archived ? 'Restore' : 'Archive'} title={archived ? 'Restore' : 'Archive'}
                    onClick={() => run(() => api.updateConversation(c.id, { archived: !archived }), archived ? undefined : c.id)}>
                    {archived ? <ArchiveRestore size={13} /> : <Archive size={13} />}
                  </button>
                  <button type="button" aria-label="Delete" title="Delete" onClick={() => remove(c)}><Trash2 size={13} /></button>
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {next !== null && <button type="button" className="conv-more" onClick={() => void more()}>Show more</button>}
      </div>
      <button type="button" className="conv-more conv-archived" onClick={() => setArchived((a) => !a)}>{archived ? 'Back to chats' : 'Archived chats'}</button>
    </section>
  )
}
