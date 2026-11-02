import { useState } from 'react'
import { BrandLogo } from '../../../../components/brand/BrandLogo'
import { MODES, hasMarkets, useModeSetting, type ThemeId } from '../../theme'
import { useAccountPanel } from '../../../../accountContext'
import { api } from '../../api'
import './SettingsTab.css'

/** Native radios (arrow keys, focus and screen-reader semantics for free). The preview swatch
 * carries data-theme itself, so it is painted with that theme's real tokens. */
export function SettingsTab({ theme }: { theme: ThemeId; onTheme?: (id: ThemeId) => void }) {
  const [mode, setMode] = useModeSetting()
  const account = useAccountPanel()
  const [erasing, setErasing] = useState(false)
  async function erase() {
    if (!window.confirm('Erase all your data: profile, transactions, every chat, saved research reports and learning progress? This cannot be undone.')) return
    setErasing(true)
    try { await api.eraseEverything(); window.location.reload() } catch { setErasing(false); window.alert('Could not erase your data. Please try again.') }
  }

  return (
    <section className="settings">
      <h1>Settings</h1>
      <h2 className="settings-h2">Appearance</h2>
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
      {account && (
        <>
          <h2 className="settings-h2">Account</h2>
          {account}
        </>
      )}
      <h2 className="settings-h2">Your data</h2>
      <p className="settings-sub">Removes everything ARIA has stored for you. Deleted chats are gone for good.</p>
      <button type="button" className="settings-danger" onClick={erase} disabled={erasing}>{erasing ? 'Erasing…' : 'Erase all my data'}</button>
      <h2 className="settings-h2">About ARIA</h2>
      <BrandLogo tagline className="settings-brand" />
      <p className="settings-sub">
        ARIA is an AI research and education tool, not a SEBI-registered adviser. <a href="#/disclaimers">Read the full disclaimers</a>.
      </p>

    </section>
  )
}
