import { useEffect, type RefObject } from 'react'

const REDUCE = typeof window !== 'undefined' && window.matchMedia('(prefers-reduced-motion: reduce)').matches

/** Flashes any .num whose value changes (green up, red down) anywhere under root, without touching the page components. */
export function useNumberFlash(root: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const el = root.current
    if (!el || REDUCE) return
    const prev = new WeakMap<Element, number>()
    const val = (n: Element) => parseFloat((n.textContent ?? '').replace(/[^0-9.-]/g, ''))
    el.querySelectorAll('.num').forEach((n) => prev.set(n, val(n)))
    const mo = new MutationObserver((ms) => {
      const seen = new Set<Element>()
      for (const m of ms) {
        const t = m.target.nodeType === Node.TEXT_NODE ? m.target.parentElement : (m.target as Element)
        const n = t?.closest('.num')
        if (!n || seen.has(n) || n.classList.contains('ux4-clock')) continue
        seen.add(n)
        const v = val(n), p = prev.get(n)
        prev.set(n, v)
        if (p === undefined || !Number.isFinite(v) || v === p) continue
        n.classList.remove('ux4-up', 'ux4-down')
        void (n as HTMLElement).offsetWidth // restart the animation
        n.classList.add(v > p ? 'ux4-up' : 'ux4-down')
      }
    })
    mo.observe(el, { subtree: true, characterData: true, childList: true })
    return () => mo.disconnect()
  }, [root])
}
