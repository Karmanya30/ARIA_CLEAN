import { useState } from 'react'
import { Check } from 'lucide-react'
import { THEMES, getTheme, setTheme, type ThemeId } from '../../theme'
import './SettingsTab.css'

/** Native radios (arrow keys, focus and screen-reader semantics for free). The preview swatch
 * carries data-theme itself, so it is painted with that theme's real tokens. */
export function SettingsTab() {
  const [theme, setChoice] = useState<ThemeId>(getTheme)

  function pick(id: ThemeId) {
    setTheme(id)
    setChoice(id)
  }

  return (
    <section className="settings">
      <h2>Settings</h2>
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
    </section>
  )
}
