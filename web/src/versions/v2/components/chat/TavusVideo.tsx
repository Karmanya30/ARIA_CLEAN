import { RotateCcw } from 'lucide-react'
import type { useTavusSession } from '../../hooks/useTavusSession'
import './TavusVideo.css'

/** Sidebar half of Tavus CVI Mode -- the video call itself. See
 * TavusTranscript for the other half (main column). */
export function TavusVideo({ session }: { session: ReturnType<typeof useTavusSession> }) {
  const { embedUrl, error, loading, ended, restart } = session

  if (error) {
    return (
      <div className="tavus-error">
        <p>Tavus integration failed: {error}</p>
        <button className="btn" onClick={restart} type="button">
          Retry Tavus Connection
        </button>
      </div>
    )
  }

  return (
    <div className="tavus-video-panel">
      <div className="banner-info">
        Talk to ARIA directly — this mode handles the whole conversation by voice.
      </div>
      {loading && <p className="tavus-loading">Provisioning Tavus CVI and ngrok tunnel… this takes ~10 seconds.</p>}
      {embedUrl && (
        <div className="tavus-iframe-wrap">
          <iframe className="tavus-iframe" src={embedUrl} title="ARIA Tavus avatar" allow="camera; microphone; autoplay" />
          {ended && (
            <div className="tavus-ended-overlay">
              <p>Call ended.</p>
              <button className="btn btn-primary" onClick={restart} type="button">
                <RotateCcw size={15} />
                Start new call
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  )
}
