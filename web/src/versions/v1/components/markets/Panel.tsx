import type { ReactNode } from 'react'
import { DataProv, Provenance } from './Provenance'
import { fmtIst } from './format'
import type { Meta } from './types'

export interface Res<T> { data: T | null; error: string | null; loading: boolean; stale: boolean }

/** Card with title + provenance and shared loading / unavailable / stale states (fixed min-height so nothing shifts). */
export function Panel<T extends { meta: Meta }>({ title, res, minH = 280, aside, ai, children, className = '' }: {
  title: string; res: Res<T>; minH?: number; aside?: ReactNode; ai?: boolean; className?: string; children: (d: T) => ReactNode
}) {
  const d = res.data
  return (
    <section className={`mk-card mk-panel ${className}`} style={{ minHeight: minH }} aria-label={title} aria-busy={res.loading}>
      <header className="mk-panel-h">
        <h2>{title}</h2>
        {aside}
      </header>
      {d ? (
        <>
          {(res.stale || d.meta.stale) && <p className="mk-note" role="status">Showing last updated {fmtIst(d.meta.as_of)}. Refreshing has failed; retrying.</p>}
          {children(d)}
          <footer className="mk-panel-f">
            <DataProv meta={d.meta} />
            {ai && <Provenance kind="ai" />}
          </footer>
        </>
      ) : res.loading ? (
        <div className="mk-skel-stack" role="status" aria-label={`Loading ${title}`}>
          {[0, 1, 2, 3, 4].map((i) => <span key={i} className="mk-skel" style={{ ['--h' as string]: '36px' }} />)}
        </div>
      ) : (
        <p className="mk-empty" role="status">{title} data is unavailable right now. We will keep retrying automatically.</p>
      )}
    </section>
  )
}
