import type { ReactNode } from 'react'
import { Info } from 'lucide-react'
import { VoiceDisk } from '../chat/VoiceDisk'
import { AvatarStage, type AvatarReply } from './AvatarStage'
import { useAvatarMode, useLook, useReplicaId } from './avatarPrefs'
import { useAvatarEngine } from './useAvatarEngine'
import './AvatarStage.css'

/** The avatar column of Local Avatar mode: the live face when the local engine is up, the ARIA disk otherwise
 * (with a notice), and nothing but a pointer to Settings when the avatar is switched off. */
export function LocalAvatarPanel({ reply, thinking, audioToken, voiceControl }: {
  reply: AvatarReply | null; thinking: boolean; audioToken?: string; voiceControl?: ReactNode
}) {
  const [mode] = useAvatarMode()
  const [replicaId] = useReplicaId()
  const [look] = useLook()
  const engine = useAvatarEngine({ replicaId, enabled: mode === 'live', framing: look.framing, bg: look.bg })

  if (mode === 'off') {
    return (
      <section className="avatar-notice avatar-off" aria-label="Avatar">
        <p><Info size={16} aria-hidden="true" /> The avatar is switched off, so replies stay as text.</p>
        <p><a href="#/settings">Open Settings</a> to turn on the Disk or Live face.</p>
        {voiceControl && <div className="avatar-voice">{voiceControl}</div>}
      </section>
    )
  }
  if (mode === 'live' && engine.status !== 'unavailable') {
    return <AvatarStage engine={engine} reply={reply} thinking={thinking} voiceControl={voiceControl} />
  }
  return (
    <>
      {mode === 'live' && (
        <p className="avatar-notice" role="status">
          <Info size={16} aria-hidden="true" />
          <span>The live face is not available{engine.reason ? ` (${engine.reason.replace(/\.$/, '')})` : ''}, so ARIA’s disk is shown.
            {/replaced/i.test(engine.reason ?? '')
              ? <> The avatar is in use in another ARIA tab. <button type="button" className="avatar-link" onClick={engine.reconnect}>Use it here</button></>
              : ' We will switch back once it is running.'}</span>
        </p>
      )}
      <VoiceDisk audioToken={audioToken} voiceControl={voiceControl} />
    </>
  )
}
