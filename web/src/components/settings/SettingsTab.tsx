import { useState } from 'react'
import { Check } from 'lucide-react'
import { adaptTone, api, setAdaptTone } from '../../api'
import { THEMES, getTheme, setTheme, type ThemeId } from '../../theme'
import './SettingsTab.css'

/** Native radios (arrow keys, focus and screen-reader semantics for free). The preview swatch
 * carries data-theme itself, so it is painted with that theme's real tokens. */
export function SettingsTab() {
  const [theme, setChoice] = useState<ThemeId>(getTheme)
  const [tone, setTone] = useState(adaptTone)
  const [status, setStatus] = useState('')

  function pick(id: ThemeId) {
    setTheme(id)
    setChoice(id)
  }

  function forget() {
    if (!window.confirm('Forget how you like ARIA to talk? This clears the style it learned about you.')) return
    api.forgetStyle().then(
      () => setStatus('Done. ARIA has forgotten how you like to talk.'),
      () => setStatus('Could not clear it. Please try again.'),
    )
  }

  return (
    <section className="settings">
      <h1>Settings</h1>
      <p className="settings-sub">
        <strong>Appearance</strong> — choose how ARIA looks. It applies instantly and is remembered on this device.
      </p>
      <div className="theme-grid" role="radiogroup" aria-label="Theme">
        {THEMES.map((t) => (
          <label key={t.id} className="theme-card">
            <input type="radio" name="theme" value={t.id} checked={theme === t.id} onChange={() => pick(t.id)} />
            <span className="tp" data-theme={t.id} aria-hidden="true">
              <span className="tp-nav">
                <i className="tp-mark" />
                <i className="tp-tab tp-on" />
                <i className="tp-tab" />
                <i className="tp-tab" />
                <i className="tp-cta" />
              </span>
              <span className="tp-main">
                <i className="tp-h" />
                <i className="tp-bar" />
                <span className="tp-cards">
                  <i />
                  <i />
                </span>
              </span>
            </span>
            <span className="theme-meta">
              <strong>{t.label}</strong>
              <span className="theme-check">
                <Check size={14} /> Selected
              </span>
            </span>
            <span className="theme-blurb">{t.blurb}</span>
          </label>
        ))}
      </div>
      <h2 className="settings-h2">Conversation</h2>
      <label className="settings-check">
        <input
          type="checkbox"
          checked={tone}
          onChange={(e) => {
            setAdaptTone(e.target.checked)
            setTone(e.target.checked)
          }}
        />
        <span>Adapt tone to how I feel</span>
      </label>
      <p className="settings-sub">
        ARIA reads your messages on this device only to choose a calmer or simpler way of answering. It never shows a mood label
        back to you, and you can turn it off any time.
      </p>
      <button type="button" className="btn" onClick={forget}>
        Forget how I like to talk
      </button>
      <p className="settings-sub" role="status" aria-live="polite">
        {status}
      </p>
    </section>
  )
}
