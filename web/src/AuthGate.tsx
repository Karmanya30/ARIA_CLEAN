import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { setAccountOwner } from './authState'
import './auth.css'

interface User { id: string; email: string }
interface State { mode: 'private' | 'accounts'; user: User | null; google_client_id: string; google_nonce?: string; allow_signup: boolean }
function notifyTabs() { try { localStorage.setItem('aria_auth_revision', crypto.randomUUID()) } catch { /* session remains server-enforced */ } }
interface GoogleIdentity {
  initialize: (options: { client_id: string; nonce?: string; callback: (response: { credential: string }) => void }) => void
  renderButton: (element: HTMLElement, options: { theme: string; size: string; text: string }) => void
}
declare global { interface Window { google?: { accounts: { id: GoogleIdentity } } } }

async function call<T>(path: string, body?: unknown): Promise<T> {
  const controller = new AbortController()
  const timeout = window.setTimeout(() => controller.abort(), 15_000)
  try {
    const response = await fetch('/api/auth/' + path, body === undefined ? { cache: 'no-store', signal: controller.signal } : {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal,
    })
    if (path === 'session' && response.status === 404) {
      throw new Error('ARIA’s backend needs an update. Run the ARIA launcher again to restart it, then retry the connection.')
    }
    let data
    try { data = await response.json() }
    catch { throw new Error('ARIA returned an unreadable response. Restart ARIA with the launcher, then retry the connection.') }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to sign in. Check your details and try again.')
    return data as T
  } catch (failure) {
    if ((failure as Error).name === 'AbortError') throw new Error('ARIA is taking too long to connect. Run the ARIA launcher again, then retry the connection.')
    if (failure instanceof TypeError) throw new Error('Unable to reach ARIA. Start it with the ARIA launcher, then retry the connection.')
    throw failure
  } finally { window.clearTimeout(timeout) }
}

function GoogleButton({ state, linked, onSuccess, onError }: { state: State; linked: boolean; onSuccess: () => void; onError: (error: string) => void }) {
  const target = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!state.google_client_id) return
    let stopped = false
    const draw = () => {
      if (stopped || !target.current || !window.google) return
      window.google.accounts.id.initialize({ client_id: state.google_client_id, nonce: state.google_nonce,
        callback: (result) => { void call(linked ? 'google/link' : 'google', { credential: result.credential }).then(onSuccess).catch((error: Error) => onError(error.message)) },
      })
      target.current.replaceChildren()
      window.google.accounts.id.renderButton(target.current, { theme: 'outline', size: 'large', text: linked ? 'continue_with' : 'signin_with' })
    }
    let script = document.querySelector<HTMLScriptElement>('script[data-aria-google]')
    if (!script) {
      script = document.createElement('script')
      script.src = 'https://accounts.google.com/gsi/client'
      script.async = true
      script.dataset.ariaGoogle = 'true'
      document.head.appendChild(script)
    }
    script.addEventListener('load', draw)
    const failed = () => onError('Google sign-in could not load. Try email and password, or retry later.')
    script.addEventListener('error', failed)
    draw()
    return () => { stopped = true; script.removeEventListener('load', draw); script.removeEventListener('error', failed) }
  }, [state.google_client_id, state.google_nonce, linked, onSuccess, onError])
  return <div ref={target} aria-label={linked ? 'Link Google account' : 'Sign in with Google'} />
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [signup, setSignup] = useState(false)
  const load = useCallback(async () => {
    try {
      const next = await call<State>('session')
      setAccountOwner(next.user?.id ?? null)
      if (next.user || next.mode === 'private') {
        const identity = next.user?.id ?? 'private'
        try {
          const previous = localStorage.getItem('aria_account_session_owner')
          // An offline admin may provision the existing private owner as an account.
          // Preserve that owner's current chat; the server still checks conversation ownership.
          const importedPrivateOwner = previous === 'private' && next.user?.id === localStorage.getItem('aria_owner_id')
          if (!importedPrivateOwner && ((previous && previous !== identity) || (next.user && previous !== identity))) {
            localStorage.removeItem('aria_session_id')
            sessionStorage.removeItem('aria_session_id')
          }
          localStorage.setItem('aria_account_session_owner', identity)
        } catch { /* active account remains in memory */ }
      }
      setState(next)
      if (next.user) setSignup(false)
      setError('')
    } catch (failure) { setError((failure as Error).message) }
  }, [])
  // The effect synchronizes external cookie/session state after an HTTP response.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { void load() }, [load])
  useEffect(() => {
    const changed = (event: StorageEvent) => { if (event.key === 'aria_auth_revision') void load() }
    window.addEventListener('storage', changed)
    return () => window.removeEventListener('storage', changed)
  }, [load])
  const success = useCallback(() => { notifyTabs(); void load(); setNotice('Google account connected.') }, [load])
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const values = new FormData(event.currentTarget)
    setBusy(true); setError('')
    try { await call(signup ? 'register' : 'login', { email: values.get('email'), password: values.get('password') }); notifyTabs(); await load() }
    catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }
  async function logout(all = false) {
    setBusy(true)
    try {
      await call(all ? 'logout-all' : 'logout', {})
      notifyTabs()
      setAccountOwner(null)
      try { localStorage.removeItem('aria_session_id'); sessionStorage.removeItem('aria_session_id') } catch { /* storage unavailable */ }
      setState(null)
      await load()
    } catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }
  if (!state) return <main className="aria-auth"><section><h1>ARIA</h1>{error ? <><p role="alert">{error}</p><button onClick={() => void load()}>Retry connection</button></> : <p>Loading ARIA…</p>}</section></main>
  if (state.mode === 'private') return children
  if (state.user) return <Fragment key={state.user.id}>
    <details className="aria-account"><summary>Account</summary><p>{state.user.email}</p>
      {state.google_client_id && <><p>Connect Google to this account</p><GoogleButton state={state} linked onSuccess={success} onError={setError} /></>}
      {notice && <p role="status">{notice}</p>}{error && <p role="alert">{error}</p>}
      <button disabled={busy} onClick={() => void logout()}>Sign out</button>
      <button disabled={busy} onClick={() => void logout(true)}>Sign out all devices</button>
    </details>{children}
  </Fragment>
  return <main className="aria-auth"><section><h1>{signup ? 'Create your ARIA account' : 'Sign in to ARIA'}</h1>
    <p>Your financial profile and conversations belong to your account.</p>
    <form onSubmit={(event) => void submit(event)}>
      <label>Email<input name="email" type="email" autoComplete="email" required maxLength={254} /></label>
      <label>Password<input name="password" type="password" autoComplete={signup ? 'new-password' : 'current-password'} required minLength={12} maxLength={128} /></label>
      <p>Use at least 12 characters.</p>
      <button disabled={busy} type="submit">{busy ? 'Please wait…' : signup ? 'Create account' : 'Sign in'}</button>
    </form>
    {state.allow_signup && <button disabled={busy} onClick={() => { setSignup(!signup); setError('') }}>{signup ? 'Already have an account? Sign in' : 'Create an account'}</button>}
    {state.google_client_id && <GoogleButton state={state} linked={false} onSuccess={success} onError={setError} />}
    {error && <p role="alert">{error}</p>}
  </section></main>
}
