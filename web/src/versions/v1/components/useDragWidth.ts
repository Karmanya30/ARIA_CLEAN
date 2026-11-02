import { useCallback, useState } from 'react'

/** A width the user can drag (and nudge with the arrow keys), remembered between visits. `fromPointer` turns the pointer's
 * x position into a width, so the same hook serves a panel dragged by its right edge and one dragged by its left edge. */
export function useDragWidth(key: string, initial: number, min: number, max: () => number, fromPointer: (x: number) => number) {
  const read = () => { try { const v = Number(localStorage.getItem(key)); return v >= min ? v : initial } catch { return initial } }
  const [width, setWidth] = useState(read)
  const [dragging, setDragging] = useState(false)
  const clamp = useCallback((w: number) => Math.round(Math.min(max(), Math.max(min, w))), [min, max])
  const save = (w: number) => { try { localStorage.setItem(key, String(w)) } catch { /* private mode */ } }
  const handle = {
    onPointerDown: (e: React.PointerEvent<HTMLElement>) => { e.currentTarget.setPointerCapture(e.pointerId); setDragging(true); e.preventDefault() },
    onPointerMove: (e: React.PointerEvent<HTMLElement>) => { if (dragging) setWidth(clamp(fromPointer(e.clientX))) },
    onPointerUp: (e: React.PointerEvent<HTMLElement>) => { e.currentTarget.releasePointerCapture(e.pointerId); setDragging(false); save(width) },
    onKeyDown: (e: React.KeyboardEvent<HTMLElement>) => {
      const step = e.key === 'ArrowLeft' ? -24 : e.key === 'ArrowRight' ? 24 : 0
      if (!step) return
      e.preventDefault()
      const next = clamp(width + (fromPointer(1) < fromPointer(0) ? -step : step)) // direction follows which edge is dragged
      setWidth(next); save(next)
    },
    onDoubleClick: () => { setWidth(initial); save(initial) },
    role: 'separator' as const, 'aria-orientation': 'vertical' as const, 'aria-valuenow': width, 'aria-valuemin': min, tabIndex: 0,
  }
  return { width, dragging, handle }
}
