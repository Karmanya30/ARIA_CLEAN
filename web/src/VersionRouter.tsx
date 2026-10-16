import { lazy, Suspense } from 'react'
import { getVersion } from './version'

/**
 * VersionRouter — top-level entry that picks which version's App to mount.
 * Each version is lazy-loaded so bundles stay separate.
 *
 * When adding a new version:
 *   1. Add a new lazy() import below.
 *   2. Wire it into the switch.
 */

const AppV1 = lazy(() => import('./versions/v1/App'))
const AppV2 = lazy(() => import('./versions/v2/App'))

function Fallback() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        minHeight: '100vh',
        fontFamily: 'system-ui, sans-serif',
        color: '#4c586f',
        fontSize: 15,
      }}
    >
      Loading ARIA…
    </div>
  )
}

export function VersionRouter() {
  const version = getVersion()

  return (
    <Suspense fallback={<Fallback />}>
      {version === 'v1' && <AppV1 />}
      {version === 'v2' && <AppV2 />}
    </Suspense>
  )
}
