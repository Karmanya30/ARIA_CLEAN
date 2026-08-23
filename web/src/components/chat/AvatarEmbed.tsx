import { api } from '../../api'
import './AvatarEmbed.css'

/** The free, self-hosted-in-browser TalkingHead 3D avatar (Conversational
 * Mode). interface/avatar/render.py builds a self-contained HTML page with
 * the model + this turn's audio embedded as base64; served over HTTP now
 * (api/routes/avatar.py's GET /avatar/render) instead of being generated
 * inline by a Python process, but the same template/asset. */
export function AvatarEmbed({ audioToken }: { audioToken: string }) {
  return (
    <iframe
      key={audioToken}
      className="avatar-embed"
      src={api.avatarUrl(audioToken)}
      title="ARIA avatar"
      allow="autoplay"
    />
  )
}
