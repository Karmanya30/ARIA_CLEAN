import { AvatarEmbed } from './AvatarEmbed'
import './ConversationalAvatar.css'

/** Conversational Mode's stage -- a decorative gradient orb until the
 * first response arrives, then the real avatar for the most recent turn.
 * Only one avatar is shown at a time (not one per historical turn, which
 * used to stack a full 3D-avatar iframe under every message in the feed
 * and got heavier the longer the conversation ran); older turns keep
 * their own plain <audio> replay control in the message list. */
export function ConversationalAvatar({ audioToken }: { audioToken?: string }) {
  if (!audioToken) {
    return <div className="hero-orb" />
  }
  return <AvatarEmbed audioToken={audioToken} />
}
