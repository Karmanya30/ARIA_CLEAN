import { lazy, Suspense } from 'react'

/** The app has one UI (Vitara Markets). The earlier versions and the version picker were removed. */
const App = lazy(() => import('./versions/v2/App'))

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
