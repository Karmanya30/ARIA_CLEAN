import { Moon, Sun } from 'lucide-react'
import { useModeSetting } from '../theme'

/** Sun/moon switch in the top bar (Vitara Markets). Flips between Light and Night; Auto is chosen in Settings. */
export function ModeToggle() {
  const [, setMode] = useModeSetting()
  // 'auto' counts as whatever it currently resolves to.
  const night = document.documentElement.dataset.mode === 'night'
  return (
    <button
      type="button"
      className="mode-toggle"
      aria-pressed={night}
      aria-label={night ? 'Switch to light mode' : 'Switch to night mode'}
      onClick={() => setMode(night ? 'light' : 'night')}
    >
      {night ? <Sun size={16} aria-hidden="true" /> : <Moon size={16} aria-hidden="true" />}
    </button>
  )
}
