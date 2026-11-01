import { ShieldAlert } from 'lucide-react'
import './Disclaimers.css'

/** Always-visible one-liner at the very top of every page (fixed; see --strip-h in Disclaimers.css). The long text is
 * used from tablet up; the short one on phones, where three lines of chrome would eat the screen. */
export function DisclaimerStrip({ onOpen }: { onOpen: () => void }) {
  const link = (
    <a
      href="#/disclaimers"
      onClick={(e) => {
        e.preventDefault()
        onOpen()
      }}
    >
      Read the full disclaimers
    </a>
  )
  return (
    <div className="aria-strip" role="note" aria-label="Disclaimer">
      <ShieldAlert size={14} aria-hidden="true" />
      <p className="aria-strip-long">
        ARIA is an AI research and education tool, not a SEBI-registered adviser; nothing here is investment advice. Markets are risky. {link}
      </p>
      <p className="aria-strip-short">
        AI research and education tool, not a SEBI-registered adviser. Not investment advice. Markets are risky. {link}
      </p>
    </div>
  )
}

/** The same sentence for use inside panels (instrument answers, report footers). */
export function DisclaimerLine({ onOpen, className = '' }: { onOpen?: () => void; className?: string }) {
  return (
    <p className={`aria-dline ${className}`} role="note">
      AI-generated and educational only, not investment advice or a recommendation. ARIA is not a SEBI-registered adviser. Data may be delayed or wrong.{' '}
      <a
        href="#/disclaimers"
        onClick={(e) => {
          if (!onOpen) return
          e.preventDefault()
          onOpen()
        }}
      >
        Read the full disclaimers
      </a>
    </p>
  )
}
