import { useDragWidth } from '../useDragWidth'

/** Width of the stock and instrument drawers, set by dragging their left edge (double-click resets, arrow keys nudge).
 * Remembered between visits; panels.css caps it at the screen width. */
export const useDrawerWidth = () =>
  useDragWidth('aria_drawer_width', 560, 420, () => window.innerWidth - 24, (x) => window.innerWidth - x)
