import { lazy, Suspense } from 'react'
import { getUi } from './uiVersion'

/** Three interfaces over the same pages: Classic (versions/v2, the default), Aurora (versions/v3) and Pulse (versions/v4). Settings → Interface switches. */
const ui = getUi()
document.documentElement.dataset.ui = ui
const App = lazy(() => (ui === 'pulse' ? import('./versions/v4/App') : ui === 'aurora' ? import('./versions/v3/App') : import('./versions/v2/App')))

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
