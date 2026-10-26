import './BrandLogo.css'

export function BrandMark({ className = '', label = '' }: { className?: string; label?: string }) {
  return <img className={`aria-brand-mark ${className}`} src="/brand/aria-mark-128.png"
    srcSet="/brand/aria-mark-128.png 1x, /brand/aria-mark-256.png 2x"
    width={128} height={128} alt={label} decoding="async" />
}

export function BrandLogo({ stacked = false, tagline = false, className = '' }: {
  stacked?: boolean; tagline?: boolean; className?: string
}) {
  return <span className={`aria-brand${stacked ? ' aria-brand--stacked' : ''} ${className}`} role="img" aria-label="ARIA">
    <BrandMark />
    <span className="aria-brand-copy" aria-hidden="true">
      <span className="aria-brand-wordmark">ARIA</span>
      {tagline && <span className="aria-brand-tagline">AI for Real Insights &amp; Analysis</span>}
    </span>
  </span>
}
