import { useEffect, useState, type FormEvent } from 'react'
import { CheckCircle2, MessageSquareHeart, Send } from 'lucide-react'
import './FeedbackTab.css'

const initial = { name: '', email: '', discovery: '', category: 'Feedback', message: '' }
export function FeedbackTab() {
  const [form, setForm] = useState(initial)
  const [other, setOther] = useState('')
  const [status, setStatus] = useState<'checking' | 'ready' | 'unavailable'>('checking')
  const [sending, setSending] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    fetch('/api/feedback/status', { signal: controller.signal, cache: 'no-store' })
      .then(async response => { if (!response.ok) throw new Error(); return response.json() })
      .then(data => setStatus(data.configured ? 'ready' : 'unavailable'))
      .catch(err => { if (err.name !== 'AbortError') setStatus('unavailable') })
    return () => controller.abort()
  }, [])
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (sending) return
    setSending(true); setError('')
    try {
      const response = await fetch('/api/feedback', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ...form, discovery: form.discovery === 'Other' ? other.trim() : form.discovery }) })
      const body = await response.json().catch(() => ({}))
      if (!response.ok || body.sent !== true) throw new Error(typeof body.detail === 'string' ? body.detail : 'We could not send your feedback. Please try again.')
      setSent(true); setForm(initial); setOther('')
    } catch (err) { setError(err instanceof Error ? err.message : 'We could not send your feedback. Please try again.') }
    finally { setSending(false) }
  }
  return <section className="fb-page" aria-labelledby="feedback-title">
    <div className="fb-heading"><div className="fb-eyebrow"><MessageSquareHeart size={16} aria-hidden="true" /> YOUR VOICE MATTERS</div><h1 id="feedback-title">Help shape ARIA</h1><p>Tell us what works, what could be better, or where you found a bug. Your feedback helps us improve.</p></div>
    <div className="fb-layout"><div className="fb-card">
      {sent ? <div className="fb-success" role="status"><CheckCircle2 size={30} aria-hidden="true" /><h2>Thank you for helping us improve.</h2><p>Your feedback has been sent to the ARIA team.</p><button className="fb-secondary" type="button" onClick={() => setSent(false)}>Send another response</button></div> : <>
      <div className="fb-card-heading"><h2>Share your feedback</h2><p>All fields are required so we can understand your experience and reach you if needed.</p></div>
      {status === 'unavailable' && <p className="fb-notice" role="status">Feedback email is not configured yet. Please try again later.</p>}
      <form className="fb-form" onSubmit={event => void submit(event)}>
        <div className="fb-row"><label>Your name<input value={form.name} onChange={e => setForm({ ...form, name: e.target.value })} autoComplete="name" maxLength={100} required placeholder="Full name" /></label>
        <label>Email address<input type="email" value={form.email} onChange={e => setForm({ ...form, email: e.target.value })} autoComplete="email" maxLength={254} required placeholder="you@example.com" /></label></div>
        <div className="fb-row"><label>What would you like to share?<select value={form.category} onChange={e => setForm({ ...form, category: e.target.value })}><option>Feedback</option><option>Bug report</option><option>Feature suggestion</option><option>Other</option></select></label>
        <label>How did you hear about ARIA?<select required value={form.discovery} onChange={e => setForm({ ...form, discovery: e.target.value })}><option value="">Select an option</option><option>Friend or colleague</option><option>College or university</option><option>Social media</option><option>Search engine</option><option>Event or presentation</option><option>Other</option></select></label></div>
        {form.discovery === 'Other' && <label>Please tell us where<input required maxLength={120} value={other} onChange={e => setOther(e.target.value)} placeholder="How did you find ARIA?" /></label>}
        <label>Your message<textarea required minLength={10} maxLength={5000} rows={7} value={form.message} onChange={e => setForm({ ...form, message: e.target.value })} placeholder="Share your experience or describe the issue and what you expected to happen." /><span className="fb-hint">For a bug, include the page and steps to reproduce it.</span></label>
        {error && <p className="fb-error" role="alert">{error}</p>}
        <div className="fb-submit"><button type="submit" disabled={sending || status !== 'ready'}>{sending ? 'Sending…' : 'Send feedback'} <Send size={16} aria-hidden="true" /></button><span>Sent directly to the ARIA team.</span></div>
      </form></>}
    </div><aside className="fb-aside"><span className="fb-aside-icon"><MessageSquareHeart size={21} /></span><h2>Every detail helps.</h2><p>Have an idea for ARIA or found something that doesn’t feel right? We’d love to hear about it.</p><div className="fb-aside-divider" /><h3>Reporting a bug?</h3><p>Tell us what you were doing, what happened and what you expected. Please leave out passwords and sensitive financial details.</p></aside></div>
  </section>
}
