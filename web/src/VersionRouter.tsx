import { lazy, Suspense } from 'react'
import { getUi } from './uiVersion'

/** Three interfaces over the same pages: Classic (versions/v2, the default), Aurora (versions/v3) and Pulse (versions/v4). Settings → Interface switches. */
const ui = getUi()
document.documentElement.dataset.ui = ui
// One lazy() per interface: with all three import()s in one expression the production build attached
// stylesheets to only one of them, so Aurora and Pulse loaded unstyled.
const App =
  ui === 'pulse' ? lazy(() => import('./versions/v4/App'))
  : ui === 'aurora' ? lazy(() => import('./versions/v3/App'))
  : lazy(() => import('./versions/v2/App'))

function Fallback() {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', fontFamily: 'system-ui, sans-serif', color: '#4c586f', fontSize: 15 }}>
      Loading ARIA…
    </div>
  )
}

export function VersionRouter() {
  return (
    <Suspense fallback={<Fallback />}>
      <App />
    </Suspense>
  )
}
