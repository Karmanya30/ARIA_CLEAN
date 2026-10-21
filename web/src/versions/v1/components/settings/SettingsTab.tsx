import { BrandLogo } from '../../../../components/brand/BrandLogo'
import { useState } from 'react'
import { Check, Layers } from 'lucide-react'
import { adaptTone, api, setAdaptTone } from '../../api'
import { MODES, THEMES, hasMarkets, setTheme, useModeSetting, type ThemeId } from '../../theme'
import { VERSIONS, getVersion, setVersion, type VersionId } from '../../version'
import { AvatarSettings } from '../../../../components/avatar/AvatarSettings'
import './SettingsTab.css'

/** Native radios (arrow keys, focus and screen-reader semantics for free). The preview swatch
 * carries data-theme itself, so it is painted with that theme's real tokens. */
export function SettingsTab({ theme, onTheme }: { theme: ThemeId; onTheme: (id: ThemeId) => void }) {
  const [tone, setTone] = useState(adaptTone)
  const [status, setStatus] = useState('')
  const [mode, setMode] = useModeSetting()
  const [currentVersion] = useState<VersionId>(getVersion)
  const [pendingVersion, setPendingVersion] = useState<VersionId | null>(null)

  function pick(id: ThemeId) {
    setTheme(id)
    onTheme(id)
  }

  function switchVersion(id: VersionId) {
    if (id === currentVersion) return
    setPendingVersion(id)
    // Small delay so the user sees the selection before reload
    setTimeout(() => setVersion(id), 400)
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
        <strong>Appearance</strong> — choose a UI version. It applies instantly and is remembered on this device.
      </p>
      <div className="theme-grid" role="radiogroup" aria-label="UI version">
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
              <i className="tp-tape" />
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
      {hasMarkets(theme) && (
        <>
          <h2 className="settings-h2">Colour mode</h2>
          <div className="seg" role="radiogroup" aria-label="Colour mode">
            {MODES.map((m) => (
              <label key={m.id}>
                <input type="radio" name="mode" value={m.id} checked={mode === m.id} onChange={() => setMode(m.id)} />
                <span>{m.label}</span>
              </label>
            ))}
          </div>
          <p className="settings-sub">Night is a dark trading-terminal look. Auto follows your device.</p>
        </>
      )}
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
        ARIA uses your messages to choose a calmer or simpler way of answering. Messages are processed by the backend and
        configured AI providers. This preference is saved on this device, and you can turn it off any time.
      </p>
      <button type="button" className="btn" onClick={forget}>
        Forget how I like to talk
      </button>
      <p className="settings-sub" role="status" aria-live="polite">
        {status}
      </p>
      <AvatarSettings />
      <h2 className="settings-h2">About ARIA</h2>
      <BrandLogo tagline className="settings-brand" />
      <p className="settings-sub">
        ARIA is an AI research and education tool, not a SEBI-registered adviser. <a href="#/disclaimers">Read the full disclaimers</a>.
      </p>

      <h2 className="settings-h2 version-h2">
        <Layers size={17} aria-hidden="true" />
        App Version
      </h2>
      <p className="settings-sub">
        <strong>Switch version</strong> — reload to a different build of ARIA. All your data and settings are kept.
      </p>
      <div className="version-grid" role="radiogroup" aria-label="App version">
        {VERSIONS.map((v) => {
          const isActive = (pendingVersion ?? currentVersion) === v.id
          return (
            <label
              key={v.id}
              className={`version-card${!v.available ? ' version-card--disabled' : ''}${isActive ? ' version-card--active' : ''}`}
            >
              <input
                type="radio"
                name="app-version"
                value={v.id}
                checked={isActive}
                disabled={!v.available}
                onChange={() => v.available && switchVersion(v.id)}
              />
              <span className="version-preview" style={{ '--v-accent': v.accent } as React.CSSProperties}>
                <span className="version-preview-bar" />
                <span className="version-preview-dots">
                  <i /><i /><i />
                </span>
                <span className="version-preview-lines">
                  <i /><i style={{ width: '60%' }} />
                </span>
              </span>
              <span className="version-meta">
                <span className="version-top">
                  <strong>{v.label}</strong>
                  <span
                    className={`version-tag version-tag--${
                      v.tag === 'Stable' ? 'stable' :
                      v.tag === 'Latest' ? 'latest' :
                      'soon'
                    }`}
                  >
                    {v.tag}
                  </span>
                </span>
                {v.date && (
                  <span className="version-date">
                    {new Date(v.date).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
                  </span>
                )}
                {isActive && v.available && (
                  <span className="version-active-badge">
                    <Check size={12} /> Active
                  </span>
                )}
              </span>
              <span className="version-blurb">{v.blurb}</span>
              {!v.available && <span className="version-coming-overlay">Coming soon</span>}
            </label>
          )
        })}
      </div>
    </section>
  )
}
