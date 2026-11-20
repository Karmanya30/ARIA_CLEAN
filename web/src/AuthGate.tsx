import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ArrowLeft, Check, Eye, EyeOff, KeyRound, Mail } from 'lucide-react'
import { setAccountOwner } from './authState'
import { BrandLogo, BrandMark } from './components/brand/BrandLogo'
import { Landing } from './Landing'
import { AccountPanelContext } from './accountContext'
import './auth.css'

interface User { id: string; email: string }
interface State {
  mode: 'private' | 'accounts'; user: User | null; google_client_id: string; google_nonce?: string; allow_signup: boolean
  password_reset?: boolean // the server can email reset links
  methods?: { password: boolean; google: boolean } // how the signed-in account can sign in
}
/** The sign-in card's screens. "reset" is opened by the link in a password-reset email (?reset=<token>). */
type Screen = 'signin' | 'signup' | 'forgot' | 'reset'
function notifyTabs() { try { localStorage.setItem('aria_auth_revision', crypto.randomUUID()) } catch { /* session remains server-enforced */ } }
interface GoogleIdentity {
  initialize: (options: { client_id: string; nonce?: string; callback: (response: { credential: string }) => void }) => void
  renderButton: (element: HTMLElement, options: { theme: string; size: string; text: string; shape?: string; width?: number; logo_alignment?: string }) => void
}
declare global { interface Window { google?: { accounts: { id: GoogleIdentity } } } }
const SESSION_ENDED = 'aria-session-ended'

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
    if (!response.ok) {
      let message = 'That did not work. Check your details and try again.'
      if (typeof (data as any)?.detail === 'string') {
        message = (data as any).detail
      } else if (Array.isArray((data as any)?.detail)) {
        message = (data as any).detail.map((e: any) => e.msg || String(e)).join('; ')
      }
      throw new Error(message)
    }
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
      const night = document.documentElement.dataset.mode === 'night'
      window.google.accounts.id.renderButton(target.current, { theme: night ? 'filled_black' : 'outline', size: 'large', shape: 'pill',
        text: 'continue_with', logo_alignment: 'center', width: Math.max(200, Math.min(400, target.current.offsetWidth || 320)) })
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

/** A password box with a show/hide button. `hint` is shown under it and read with it. */
function PasswordField({ id, label, name, autoComplete, minLength, hint, show, onToggle }: {
  id: string; label: string; name: string; autoComplete: string; minLength?: number; hint?: string; show: boolean; onToggle: () => void
}) {
  return <div className="auth-field">
    <label htmlFor={id}>{label}</label>
    <div className="auth-password">
      <input id={id} name={name} type={show ? 'text' : 'password'} autoComplete={autoComplete} required minLength={minLength} maxLength={128}
        aria-describedby={hint ? `${id}-hint` : undefined} />
      <button type="button" aria-label={show ? 'Hide password' : 'Show password'} aria-pressed={show} onClick={onToggle}>
        {show ? <EyeOff size={18} aria-hidden="true" /> : <Eye size={18} aria-hidden="true" />}
      </button>
    </div>
    {hint && <p id={`${id}-hint`} className="auth-hint">{hint}</p>}
  </div>
}

/** Settings → Account: who is signed in, how they can sign in, change (or set) the password, link Google, sign out. */
function AccountPanel({ state, onChanged, onLogout, busy }: { state: State; onChanged: () => Promise<void>; onLogout: (all: boolean) => void; busy: boolean }) {
  const [notice, setNotice] = useState('')
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [show, setShow] = useState(false)
  const hasPassword = state.methods?.password ?? true
  const googleLinked = state.methods?.google ?? false
  const linked = useCallback(() => { notifyTabs(); setError(''); setNotice('Google account linked. You can now sign in with Google too.'); void onChanged() }, [onChanged])
  async function changePassword(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const values = new FormData(form)
    setNotice(''); setError('')
    if (values.get('new_password') !== values.get('confirm_password')) { setError('The new passwords do not match.'); return }
    setSaving(true)
    try {
      await call('password/change', { current_password: values.get('current_password') ?? '', new_password: values.get('new_password') })
      form.reset()
      setNotice(hasPassword ? 'Password changed. Other devices were signed out.' : 'Password set. You can now sign in with your email and password too.')
      notifyTabs(); await onChanged()
    } catch (failure) { setError((failure as Error).message) }
    finally { setSaving(false) }
  }
  return <div className="aria-account-panel">
    <p>Signed in as <strong>{state.user!.email}</strong></p>
    <ul className="aria-methods" aria-label="Ways to sign in">
      <li className={hasPassword ? 'on' : ''}>{hasPassword ? <Check size={14} aria-hidden="true" /> : <KeyRound size={14} aria-hidden="true" />} Password {hasPassword ? 'set' : 'not set'}</li>
      {state.google_client_id && <li className={googleLinked ? 'on' : ''}>{googleLinked ? <Check size={14} aria-hidden="true" /> : <Mail size={14} aria-hidden="true" />} Google {googleLinked ? 'linked' : 'not linked'}</li>}
    </ul>

    <form className="aria-password-form" onSubmit={(event) => void changePassword(event)} aria-label={hasPassword ? 'Change password' : 'Set a password'}>
      <h3>{hasPassword ? 'Change password' : 'Set a password'}</h3>
      {!hasPassword && <p>Your account uses Google. Add a password to also sign in with your email.</p>}
      {hasPassword && <PasswordField id="aria-current-password" label="Current password" name="current_password" autoComplete="current-password" show={show} onToggle={() => setShow(!show)} />}
      <PasswordField id="aria-new-password" label="New password" name="new_password" autoComplete="new-password" minLength={8} hint="At least 8 characters." show={show} onToggle={() => setShow(!show)} />
      <PasswordField id="aria-confirm-new-password" label="Confirm new password" name="confirm_password" autoComplete="new-password" minLength={8} show={show} onToggle={() => setShow(!show)} />
      <button className="btn btn-primary" type="submit" disabled={saving}>{saving ? 'Saving…' : hasPassword ? 'Change password' : 'Set password'}</button>
    </form>

    {state.google_client_id && !googleLinked && <div className="aria-link-google"><p>Link your Google account to sign in with one click.</p><GoogleButton state={state} linked onSuccess={linked} onError={setError} /></div>}
    {notice && <p role="status" className="aria-account-notice">{notice}</p>}
    {error && <p role="alert">{error}</p>}
    <div className="aria-account-actions">
      <button className="btn" disabled={busy} onClick={() => onLogout(false)}>Sign out</button>
      <button className="btn" disabled={busy} onClick={() => onLogout(true)}>Sign out all devices</button>
    </div>
  </div>
}

export function AuthGate({ children }: { children: ReactNode }) {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [busy, setBusy] = useState(false)
  // A reset link opens the reset screen; its token is taken out of the address bar once read.
  const [resetToken] = useState(() => new URLSearchParams(window.location.search).get('reset'))
  const [screen, setScreen] = useState<Screen>(resetToken ? 'reset' : 'signin')
  const [showPassword, setShowPassword] = useState(false)
  // Visitors to the bare address see the landing page; deep links (#/profile) and email links go straight to sign-in.
  const [view, setView] = useState<'landing' | 'auth'>(() => {
    const q = new URLSearchParams(window.location.search)
    return ['', '#', '#/'].includes(window.location.hash) && !q.has('verify') && !q.has('reset') ? 'landing' : 'auth'
  })
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
      if (next.user) setScreen('signin')
      setError('')
    } catch (failure) { setError((failure as Error).message) }
  }, [])
  // The effect synchronizes external cookie/session state after an HTTP response.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => {
    if (resetToken) window.history.replaceState(null, '', window.location.pathname + window.location.hash) // keep the token out of history
    // The link in the sign-up email opens the app with ?verify=<token>: confirm the address, then load the new session.
    const token = new URLSearchParams(window.location.search).get('verify')
    if (!token) { void load(); return }
    window.history.replaceState(null, '', window.location.pathname + window.location.hash)
    call('verify', { token }).then(() => { notifyTabs(); return load() }).catch((failure) => { setError((failure as Error).message); return load() })
  }, [load, resetToken])
  useEffect(() => {
    const changed = (event: StorageEvent) => { if (event.key === 'aria_auth_revision') void load() }
    window.addEventListener('storage', changed)
    return () => window.removeEventListener('storage', changed)
  }, [load])
  // A session that ends while ARIA is open (expired, or signed out elsewhere) makes the app's API calls answer 401: go back to sign-in.
  const signedIn = Boolean(state?.user)
  useEffect(() => {
    if (!signedIn) return
    const original = window.fetch
    window.fetch = async (...args: Parameters<typeof fetch>) => {
      const response = await original(...args)
      const url = args[0] instanceof Request ? args[0].url : String(args[0])
      if (response.status === 401 && url.includes('/api/') && !url.includes('/api/auth/')) window.dispatchEvent(new Event(SESSION_ENDED))
      return response
    }
    const ended = () => { setNotice('Your session has ended. Please sign in again.'); setView('auth'); void load() }
    window.addEventListener(SESSION_ENDED, ended)
    return () => { window.fetch = original; window.removeEventListener(SESSION_ENDED, ended) }
  }, [signedIn, load])
  const signedInWithGoogle = useCallback(() => { notifyTabs(); void load() }, [load])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (busy) return
    const values = new FormData(event.currentTarget)
    setError(''); setNotice('')
    if ((screen === 'signup' || screen === 'reset') && values.get('password') !== values.get('confirm')) { setError('The passwords do not match.'); return }
    setBusy(true)
    try {
      if (screen === 'forgot') {
        const result = await call<{ message: string }>('password/forgot', { email: values.get('email') })
        setNotice(result.message)
        return
      }
      if (screen === 'reset') {
        await call('password/reset', { token: resetToken, password: values.get('password') })
        notifyTabs(); await load()
        return
      }
      const result = await call<{ pending?: boolean; message?: string }>(screen === 'signup' ? 'register' : 'login', { email: values.get('email'), password: values.get('password') })
      if (result?.pending) { setNotice(result.message ?? 'Check your email to finish signing up.'); return }
      notifyTabs(); await load()
    }
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
      setNotice(all ? 'Signed out on every device.' : 'Signed out.')
      setView('auth')
      await load()
    } catch (failure) { setError((failure as Error).message) }
    finally { setBusy(false) }
  }
  if (!state) return <main className="aria-auth"><section><BrandLogo stacked tagline className="aria-auth-brand" /><h1>ARIA</h1>{error ? <><p role="alert">{error}</p><button onClick={() => void load()}>Retry connection</button></> : <p>Loading ARIA…</p>}</section></main>
  if (state.mode === 'private') return children
  if (state.user) {
    const panel = <AccountPanel state={state} onChanged={load} onLogout={(all) => void logout(all)} busy={busy} />
    return <Fragment key={state.user.id}><AccountPanelContext.Provider value={panel}>{children}</AccountPanelContext.Provider></Fragment>
  }
  const google = Boolean(state.google_client_id)
  const go = (next: Screen) => { setScreen(next); setError(''); setNotice(''); setShowPassword(false) }
  const openAuth = (asSignup: boolean) => { go(asSignup ? 'signup' : 'signin'); setView('auth'); window.scrollTo(0, 0) }
  if (view === 'landing') return <Landing canSignUp={state.allow_signup} onSignIn={() => openAuth(false)} onGetStarted={() => openAuth(state.allow_signup)} />
  const TITLES: Record<Screen, [string, string]> = {
    signin: ['Sign in to ARIA', 'Welcome back. Your profile and conversations are waiting.'],
    signup: ['Create your ARIA account', 'Free to use. Your profile and chats stay private to your account.'],
    forgot: ['Reset your password', 'Enter your account’s email and we will send you a link to choose a new password.'],
    reset: ['Choose a new password', 'This signs you out on every other device and signs you in here.'],
  }
  const [title, sub] = TITLES[screen]
  const withEmail = screen !== 'reset'
  const withPassword = screen !== 'forgot'
  const newPassword = screen === 'signup' || screen === 'reset'
  return <main className="aria-auth aria-auth--split">
    <aside className="auth-aside" aria-hidden="true">
      <BrandLogo tagline className="auth-aside-brand" />
      <div>
        <p className="auth-aside-title">One assistant for your money</p>
        <ul>
          {['Plans built from your own numbers', 'Finance lessons at your pace', 'Market moves explained with real headlines', 'Company research with sourced figures']
            .map(item => <li key={item}><Check size={18} />{item}</li>)}
        </ul>
      </div>
      <p className="auth-aside-note">Educational only. ARIA never gives buy or sell tips.</p>
    </aside>
    <section className="auth-card">
      {screen === 'forgot' || screen === 'reset'
        ? <button type="button" className="auth-back" onClick={() => go('signin')}><ArrowLeft size={16} aria-hidden="true" /> Back to sign in</button>
        : <button type="button" className="auth-back" onClick={() => { setView('landing'); setError(''); setNotice('') }}><ArrowLeft size={16} aria-hidden="true" /> Back to home</button>}
      <BrandMark className="auth-mark" />
      <h1>{title}</h1>
      <p className="auth-sub">{sub}</p>
      {google && (screen === 'signin' || screen === 'signup') && <>
        <div className="auth-google"><GoogleButton state={state} linked={false} onSuccess={signedInWithGoogle} onError={setError} /></div>
        <p className="auth-divider"><span>or use email</span></p>
      </>}
      {screen === 'forgot' && !state.password_reset
        ? <p className="auth-notice">Password reset by email is not set up on this server yet. Please contact the ARIA team to reset your password.</p>
        : <form key={screen} onSubmit={(event) => void submit(event)}>
          {withEmail && <label className="auth-field">Email<input name="email" type="email" autoComplete="email" required maxLength={254} placeholder="you@example.com" /></label>}
          {withPassword && <>
            <div className="auth-field-row">
              {screen === 'signin' && <button type="button" className="auth-link auth-forgot" onClick={() => go('forgot')}>Forgot password?</button>}
              <PasswordField id="aria-password" label={screen === 'reset' ? 'New password' : 'Password'} name="password"
                autoComplete={newPassword ? 'new-password' : 'current-password'} minLength={newPassword ? 8 : undefined}
                hint={newPassword ? 'At least 8 characters.' : undefined} show={showPassword} onToggle={() => setShowPassword(!showPassword)} />
            </div>
            {newPassword && <PasswordField id="aria-confirm" label="Confirm password" name="confirm" autoComplete="new-password" minLength={8}
              show={showPassword} onToggle={() => setShowPassword(!showPassword)} />}
          </>}
          <button className="auth-submit" disabled={busy} type="submit">
            {busy ? 'Please wait…' : { signin: 'Sign in', signup: 'Create account', forgot: 'Send reset link', reset: 'Save new password' }[screen]}
          </button>
        </form>}
      {notice && <p role="status" className="auth-notice">{notice}</p>}
      {error && <p role="alert" className="auth-error">{error}
        {screen === 'signin' && google && error === 'Email or password is incorrect.' && <> Signed up with Google? Use “Continue with Google” above.</>}</p>}
      {screen === 'reset' && error.startsWith('This reset link') && <p className="auth-switch"><button type="button" className="auth-link" onClick={() => go('forgot')}>Send a new reset link</button></p>}
      {state.allow_signup && (screen === 'signin' || screen === 'signup') && <p className="auth-switch">{screen === 'signup' ? 'Already have an account?' : 'New to ARIA?'}{' '}
        <button type="button" className="auth-link" disabled={busy} onClick={() => go(screen === 'signup' ? 'signin' : 'signup')}>{screen === 'signup' ? 'Sign in' : 'Create an account'}</button></p>}
      {!state.allow_signup && !google && screen === 'signin' && <p className="auth-switch">New accounts are by invitation for now.</p>}
    </section>
  </main>
}
