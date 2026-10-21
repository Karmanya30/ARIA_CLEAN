import { useCallback, useEffect, useRef, useState } from 'react'
import { Check, Trash2, Upload, UserRound } from 'lucide-react'
import { AVATAR_MODES, BACKGROUNDS, FRAMINGS, useAvatarMode, useLook, useReplicaId } from './avatarPrefs'
import { engineApi, useEngineHealth } from './engineApi'
import type { Replica } from './protocol'
import './AvatarSettings.css'

const MAX_UPLOAD_MB = 60

function Preview({ replica }: { replica: Replica }) {
  const [broken, setBroken] = useState(false)
  return broken
    ? <span className="rep-fallback" aria-hidden="true"><UserRound size={28} /></span>
    : <img className="rep-img" src={engineApi.previewUrl(replica)} alt="" loading="lazy" onError={() => setBroken(true)} />
}

/** Settings > Avatar: mode selector, engine status chip and the replica (face) manager. */
export function AvatarSettings() {
  const [mode, setMode] = useAvatarMode()
  const [selected, setSelected] = useReplicaId()
  const [look, setLook] = useLook()
  const { health, error, checked, rttMs } = useEngineHealth(true)
  const [replicas, setReplicas] = useState<Replica[] | null>(null)
  const [listError, setListError] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null) // 'upload' or the replica id being deleted
  const [progress, setProgress] = useState(0)
  const [problem, setProblem] = useState<string | null>(null)
  const [notice, setNotice] = useState('')
  const fileRef = useRef<HTMLInputElement>(null)
  const [name, setName] = useState('')
  const up = !!health && health.ready !== false

  const load = useCallback(async () => {
    try { setReplicas(await engineApi.replicas()); setListError(null) }
    catch (e) { setReplicas(null); setListError(e instanceof Error ? e.message : 'Could not load the faces.') }
  }, [])
  useEffect(() => { if (up) void load() }, [up, load])

  const active = selected && replicas?.some((r) => r.replica_id === selected) ? selected : health?.replica_default ?? replicas?.[0]?.replica_id ?? null

  async function upload(file: File | undefined) {
    if (!file) return
    setProblem(null); setNotice('')
    if (!/^(image|video)\//.test(file.type)) { setProblem('Choose a photo (JPG or PNG) or a short video (MP4 or WebM).'); return }
    if (file.size > MAX_UPLOAD_MB * 1024 * 1024) { setProblem(`That file is over ${MAX_UPLOAD_MB} MB. Use a smaller photo or a shorter clip.`); return }
    setBusy('upload'); setProgress(0)
    try {
      const { replica_id } = await engineApi.createReplica(file, name.trim() || undefined, setProgress)
      setSelected(replica_id)
      setName('')
      setNotice('Face added and selected.')
      await load()
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Upload failed.')
    } finally {
      setBusy(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  async function remove(r: Replica) {
    if (!window.confirm(`Delete the face “${r.name || r.replica_id}”? This cannot be undone.`)) return
    setProblem(null); setNotice(''); setBusy(r.replica_id)
    try {
      await engineApi.deleteReplica(r.replica_id)
      if (selected === r.replica_id) setSelected(null)
      setNotice('Face deleted.')
      await load()
    } catch (e) {
      setProblem(e instanceof Error ? e.message : 'Could not delete that face.')
    } finally { setBusy(null) }
  }

  const stat = (label: string, value: string | number | null | undefined) =>
    value === null || value === undefined || value === '' ? null : <span className="av-stat"><span>{label}</span> {value}</span>

  return (
    <>
      <h2 className="settings-h2">Avatar</h2>
      <p className="settings-sub">
        How ARIA appears when it speaks in <strong>Local Avatar (Live Face)</strong> chat mode. The live face is generated on this computer;
        nothing is sent to a cloud service.
      </p>
      <div className="seg" role="radiogroup" aria-label="Avatar mode">
        {AVATAR_MODES.map((m) => (
          <label key={m.id}>
            <input type="radio" name="avatar-mode" value={m.id} checked={mode === m.id} onChange={() => setMode(m.id)} />
            <span>{m.label}</span>
          </label>
        ))}
      </div>
      <p className="settings-sub">{AVATAR_MODES.find((m) => m.id === mode)?.blurb}</p>

      <div className={`av-chip${up ? ' av-chip-up' : ''}`} role="status" aria-live="polite">
        <span className="av-dot" aria-hidden="true" />
        {!checked ? <span>Checking the avatar engine…</span> : health && !up ? <span><strong>Engine starting.</strong> {health.detail ?? 'Loading models'}. This takes about 40 seconds.</span> : up ? (
          <>
            <strong>Engine running</strong>
            {stat('Backend', health.backend)}
            {stat('FPS', health.fps !== undefined ? Math.round(health.fps) : null)}
            {stat('GPU', health.gpu)}
            {stat('VRAM', health.vram_used_mb !== undefined ? `${(health.vram_used_mb / 1024).toFixed(1)} GB` : null)}
            {stat('Latency', rttMs !== null ? `${rttMs} ms` : null)}
          </>
        ) : (
          <span><strong>Engine not running.</strong> {error ?? ''} {mode === 'live' && 'ARIA uses the disk until it is.'}</span>
        )}
      </div>

      {mode === 'live' && (
        <section className="av-replicas" aria-labelledby="av-faces-h">
          <h3 id="av-faces-h" className="av-h3">Faces</h3>
          {!up ? <p className="settings-sub">Start the avatar engine to see and add faces.</p> : (
            <>
              {listError && <p className="av-error" role="alert">{listError}</p>}
              {replicas && replicas.length === 0 && <p className="settings-sub">No faces yet. Add a clear, front-facing photo or a short video of the person who should appear.</p>}
              {replicas && replicas.length > 0 && (
                <div className="rep-grid" role="radiogroup" aria-label="Active face">
                  {replicas.map((r) => (
                    <div key={r.replica_id} className={`rep-card${active === r.replica_id ? ' rep-active' : ''}`}>
                      <label className="rep-pick">
                        <input type="radio" name="replica" value={r.replica_id} checked={active === r.replica_id} onChange={() => setSelected(r.replica_id)} />
                        <span className="rep-thumb"><Preview replica={r} /></span>
                        <span className="rep-name">{r.name || r.replica_id}</span>
                        {active === r.replica_id && <span className="rep-badge"><Check size={12} aria-hidden="true" /> Active</span>}
                      </label>
                      <button type="button" className="rep-del" onClick={() => void remove(r)} disabled={busy !== null || r.replica_id === health?.replica_default}
                        title={r.replica_id === health?.replica_default ? 'The default face cannot be deleted' : undefined}
                        aria-label={`Delete face ${r.name || r.replica_id}`}>
                        <Trash2 size={15} aria-hidden="true" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
              <div className="rep-look">
                <label className="av-field"><span>Framing</span>
                  <select className="input" value={look.framing} onChange={(e) => setLook({ ...look, framing: e.target.value as typeof look.framing })}>
                    {FRAMINGS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
                  </select></label>
                <label className="av-field"><span>Background</span>
                  <select className="input" value={BACKGROUNDS.some((b) => b.id === look.bg) ? look.bg : 'original'} onChange={(e) => setLook({ ...look, bg: e.target.value })}>
                    {BACKGROUNDS.map((b) => <option key={b.id} value={b.id}>{b.label}</option>)}
                  </select></label>
              </div>
              <div className="rep-add">
                <label className="av-field">
                  <span>Name (optional)</span>
                  <input className="input" value={name} maxLength={60} onChange={(e) => setName(e.target.value)} disabled={busy !== null} />
                </label>
                <input ref={fileRef} id="rep-file" className="sr-only" type="file" accept="image/*,video/*" disabled={busy !== null}
                  onChange={(e) => void upload(e.target.files?.[0])} />
                <label htmlFor="rep-file" className={`btn rep-upload${busy !== null ? ' is-disabled' : ''}`}>
                  <Upload size={15} aria-hidden="true" /> {busy === 'upload' ? 'Uploading…' : 'Add a photo or video'}
                </label>
              </div>
              {busy === 'upload' && (
                <>
                  <div className="av-progress" role="progressbar" aria-label="Upload progress" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress * 100)}>
                    <span style={{ width: `${Math.round(progress * 100)}%` }} />
                  </div>
                  <p className="av-progress-text">{progress >= 1 ? 'Uploaded. Preparing the face…' : `Uploading… ${Math.round(progress * 100)}%`}</p>
                </>
              )}
              <p className="settings-sub rep-hint">Only use a photo or video of yourself, or of someone who has agreed. Avatars are always labelled as AI-generated.</p>
              {problem && <p className="av-error" role="alert">{problem}</p>}
              <p className="sr-only" role="status" aria-live="polite">{notice}</p>
              {notice && <p className="av-ok" aria-hidden="true">{notice}</p>}
            </>
          )}
        </section>
      )}
    </>
  )
}
