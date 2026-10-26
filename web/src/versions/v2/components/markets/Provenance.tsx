/** Small chip saying where a number came from: fetched data, our own calculation, or AI output. */
export function Provenance({ kind, source, asOf, delayMin }: { kind: 'data' | 'calc' | 'ai'; source?: string; asOf?: string; delayMin?: number }) {
  const parts = [kind === 'data' ? 'Data' : kind === 'calc' ? 'Calculated' : 'AI']
  if (kind === 'data') {
    if (source) parts.push(source)
    if (delayMin) parts.push(`delayed ~${delayMin} min`)
    if (asOf) parts.push(asOf)
  }
  return <span className="mk-chip">{parts.join(' · ')}</span>
}

import type { Meta } from './types'
import { fmtIst } from './format'
/** Provenance chip for a fetched-data block, straight from the response meta. */
export const DataProv = ({ meta }: { meta: Meta }) => <Provenance kind="data" source={meta.source} delayMin={/yahoo/i.test(meta.source) ? meta.delay_min : undefined} asOf={fmtIst(meta.as_of)} />
