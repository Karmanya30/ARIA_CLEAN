/**
 * ARIA Version Registry
 *
 * Each entry represents a complete snapshot of the app UI.
 * The active version is persisted in localStorage.
 *
 * To add a new version:
 *   1. Create `src/versions/vN/App.tsx` with the new UI entry point.
 *   2. Add an entry to VERSIONS below.
 *   3. Add a lazy import in VersionRouter.tsx.
 */

export type VersionId = 'v1' | 'v2'

export interface VersionMeta {
  id: VersionId
  label: string
  tag: string       // short badge text, e.g. "Latest", "Stable"
  blurb: string
  date: string      // ISO date of the snapshot
  accent: string    // hex colour used in the version card preview
  available: boolean
}

export const VERSIONS: VersionMeta[] = [
  {
    id: 'v1',
    label: 'Version 1',
    tag: 'Stable',
    blurb:
      'The original ARIA interface — classic sidebar, Vitara themes, chat-first AI research, Markets dashboard, Explore, Progress and Research reports.',
    date: '2026-10-14',
    accent: '#2953b8',
    available: true,
  },
  {
    id: 'v2',
    label: 'Version 2',
    tag: 'New',
    blurb:
      'Redesigned chat experience — glassmorphism UI, animated thinking dots, voice waveforms, modern message bubbles and smooth transitions throughout.',
    date: '2026-10-15',
    accent: '#0f8a5f',
    available: true,
  },
]

const VERSION_KEY = 'aria_version'

export function getVersion(): VersionId {
  try {
    const saved = localStorage.getItem(VERSION_KEY)
    return VERSIONS.find((v) => v.id === saved && v.available)?.id ?? 'v1'
  } catch {
    return 'v1'
  }
}

export function setVersion(id: VersionId) {
  try {
    localStorage.setItem(VERSION_KEY, id)
  } catch {
    // Storage blocked: choice applies until tab is closed.
  }
  // Hard reload so the new version's entry-point is fully initialised.
  window.location.reload()
}
