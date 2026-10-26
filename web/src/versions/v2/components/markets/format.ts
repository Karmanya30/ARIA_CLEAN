/** Plain number with Indian digit grouping (12,34,567.89). */
export const fmtNum = (n: number, digits = 2) =>
  Number.isFinite(n) ? n.toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '–'
export const fmtInr = (n: number) => (Number.isFinite(n) ? `₹${fmtNum(n)}` : '–')
export const fmtPct = (n: number, digits = 2, sign = true) =>
  Number.isFinite(n) ? `${sign && n > 0 ? '+' : ''}${n.toFixed(digits)}%` : '–'
/** Rupee amount given in crore, shown as Cr or L Cr (1 L Cr = 1,00,000 Cr). */
export const fmtCr = (cr: number) =>
  !Number.isFinite(cr) ? '–' : Math.abs(cr) >= 1e5 ? `₹${fmtNum(cr / 1e5)} L Cr` : `₹${fmtNum(cr, cr >= 100 ? 0 : 2)} Cr`
/** ISO timestamp -> "9 Oct, 15:15 IST". */
export const fmtIst = (iso?: string) =>
  iso ? `${new Date(iso).toLocaleString('en-IN', { timeZone: 'Asia/Kolkata', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false })} IST` : ''
export const fmtAge = (h: number) => (h < 1 ? `${Math.max(1, Math.round(h * 60))} min ago` : h < 24 ? `${Math.round(h)} h ago` : `${Math.round(h / 24)} d ago`)
