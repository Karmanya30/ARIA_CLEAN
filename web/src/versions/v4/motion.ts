import { useEffect, type RefObject } from 'react'

/** Pulse motion (effect lab options 2 and 5): card depth with a pointer light, magnetic primary buttons, and cards that
 * rise into place as they scroll into view. All of it works on the existing page markup through class selectors. */
const REDUCE = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches
const FINE = typeof window !== 'undefined' && window.matchMedia('(hover: hover) and (pointer: fine)').matches
export const SURFACES = '.card, .mk-card, .ri-card, .fb-card, .template-card, .ux4-kpi, .ux4-chart'
const MAGNETS = '.btn-primary, .ri-primary, .ux4-new, .rt-create button[type="submit"], .composer-submit, .mk-chipbtn'

/** Tilt toward the pointer (smaller angle on wide cards) plus --px/--py for the light that follows it. */
export function useDepth(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current
    if (!el || REDUCE || !FINE) return
    let last: HTMLElement | null = null
    const flat = (n: HTMLElement | null) => { n?.style.setProperty('--rx', '0deg'); n?.style.setProperty('--ry', '0deg') }
    const move = (e: PointerEvent) => {
      const card = (e.target as HTMLElement).closest<HTMLElement>(SURFACES)
      if (card !== last) { flat(last); last = card }
      if (!card) return
      const r = card.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top
      const max = 7 * Math.min(1, 380 / r.width) // a full-width panel barely tilts; a tile tilts properly
      card.style.setProperty('--px', `${x}px`); card.style.setProperty('--py', `${y}px`)
      card.style.setProperty('--rx', `${(y / r.height - 0.5) * -max}deg`); card.style.setProperty('--ry', `${(x / r.width - 0.5) * max}deg`)
    }
    const leave = () => { flat(last); last = null }
    el.addEventListener('pointermove', move)
    el.addEventListener('pointerleave', leave)
    return () => { el.removeEventListener('pointermove', move); el.removeEventListener('pointerleave', leave) }
  }, [root])
}

/** Primary buttons lean toward a nearby pointer. */
export function useMagnets() {
  useEffect(() => {
    if (REDUCE || !FINE) return
    let raf = 0, px = 0, py = 0
    const tick = () => {
      raf = 0
      document.querySelectorAll<HTMLElement>(MAGNETS).forEach((b) => {
        const r = b.getBoundingClientRect()
        if (!r.width) return
        const dx = px - (r.left + r.width / 2), dy = py - (r.top + r.height / 2), reach = Math.max(r.width, r.height) / 2 + 60
        b.style.translate = Math.hypot(dx, dy) < reach ? `${dx * 0.18}px ${dy * 0.28}px` : ''
      })
    }
    const move = (e: PointerEvent) => { px = e.clientX; py = e.clientY; if (!raf) raf = requestAnimationFrame(tick) }
    window.addEventListener('pointermove', move)
    return () => { window.removeEventListener('pointermove', move); cancelAnimationFrame(raf) }
  }, [])
}

/** Cards rise into place the first time they scroll into view, including ones that appear after data loads. */
export function useScrollReveal(root: RefObject<HTMLElement | null>, page: string) {
  useEffect(() => {
    const el = root.current
    if (!el || REDUCE) return
    const io = new IntersectionObserver((es) => es.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add('ux4-in'); io.unobserve(e.target) }
    }), { threshold: 0.08, rootMargin: '0px 0px -40px 0px' })
    let raf = 0
    const scan = () => {
      raf = 0
      el.querySelectorAll<HTMLElement>(SURFACES).forEach((n) => {
        if (n.classList.contains('ux4-rv') || n.parentElement?.closest('.ux4-rv')) return // nested cards ride along with their parent
        n.classList.add('ux4-rv')
        io.observe(n)
      })
    }
    scan()
    const mo = new MutationObserver(() => { if (!raf) raf = requestAnimationFrame(scan) })
    mo.observe(el, { childList: true, subtree: true })
    return () => { io.disconnect(); mo.disconnect(); cancelAnimationFrame(raf) }
  }, [root, page])
}
