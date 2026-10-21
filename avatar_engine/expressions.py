"""Small local warps on the (scaled) photo: blink, gaze shift, brow lift/furrow, smile. Everything is a cv2.remap on a
small region, so it costs well under a millisecond. Landmarks are the 68-point face set (DWPose), already scaled to `img`."""
from __future__ import annotations

import cv2
import numpy as np

R_EYE, L_EYE = slice(36, 42), slice(42, 48)
R_BROW, L_BROW = slice(17, 22), slice(22, 27)   # right brow: outer->inner; left brow: inner->outer
MOUTH_L, MOUTH_R = 48, 54


def _bounds(img, x1, y1, x2, y2):
    h, w = img.shape[:2]
    return max(0, int(x1)), max(0, int(y1)), min(w, int(x2)), min(h, int(y2))


def eye(img: np.ndarray, pts: np.ndarray, blink: float, gaze: tuple[float, float] = (0.0, 0.0)) -> None:
    """In-place. blink 0=open..1=closed: the upper lid is stretched down over the eye and the eyeball squeezed (a thin lash
    line stays). gaze (dx,dy) in px shifts the eyeball content inside the lids."""
    if blink < 0.01 and abs(gaze[0]) < 0.05 and abs(gaze[1]) < 0.05:
        return
    x1, y1 = pts.min(0)
    x2, y2 = pts.max(0)
    w, he = x2 - x1, max(y2 - y1, 2.0)
    X1, Y1, X2, Y2 = _bounds(img, x1 - .3 * w, y1 - .75 * w, x2 + .3 * w, y2 + .45 * w)
    if X2 - X1 < 8 or Y2 - Y1 < 8:
        return
    roi = img[Y1:Y2, X1:X2]
    ys = np.arange(Y1, Y2, dtype=np.float32)
    yc = y1 + min(max(blink, 0.0), 1.0) * (he * 0.88)
    src_y = np.interp(ys, [Y1, yc, y2, Y2], [Y1, y1, y2, Y2]).astype(np.float32)
    mx = np.tile(np.arange(X1, X2, dtype=np.float32), (Y2 - Y1, 1))
    my = np.tile(src_y[:, None], (1, X2 - X1))
    if abs(gaze[0]) > 0.05 or abs(gaze[1]) > 0.05:
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        e = np.clip(1 - ((mx - cx) / (w * .5)) ** 2 - ((my - cy) / (he * .8)) ** 2, 0, 1)
        mx = mx - gaze[0] * e
        my = my - gaze[1] * e
    img[Y1:Y2, X1:X2] = cv2.remap(roi, mx - X1, my - Y1, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def _bump(img, center, sx, sy, dx, dy, pad=2.5):
    """Move content around a centre by (dx,dy) px with a gaussian falloff."""
    cx, cy = center
    X1, Y1, X2, Y2 = _bounds(img, cx - pad * sx, cy - pad * sy, cx + pad * sx, cy + pad * sy)
    if X2 - X1 < 6 or Y2 - Y1 < 6:
        return
    gx, gy = np.meshgrid(np.arange(X1, X2, dtype=np.float32), np.arange(Y1, Y2, dtype=np.float32))
    g = np.exp(-(((gx - cx) / sx) ** 2 + ((gy - cy) / sy) ** 2) / 2).astype(np.float32)
    img[Y1:Y2, X1:X2] = cv2.remap(img[Y1:Y2, X1:X2], gx - X1 - dx * g, gy - Y1 - dy * g, cv2.INTER_LINEAR,
                                  borderMode=cv2.BORDER_REPLICATE)


def brows(img: np.ndarray, lm: np.ndarray, lift: float, inner: float = 0.0) -> None:
    """lift (+ up / - down, in px) moves the whole brow; inner raises only the inner end (worried look)."""
    if abs(lift) < 0.05 and abs(inner) < 0.05:
        return
    for sl, inner_idx in ((R_BROW, -1), (L_BROW, 0)):
        p = lm[sl]
        c, wdt = p.mean(0), max(np.ptp(p[:, 0]), 8.0)
        if abs(lift) >= 0.05:
            _bump(img, c, wdt * .45, wdt * .18, 0, -lift)
        if abs(inner) >= 0.05:
            _bump(img, p[inner_idx], wdt * .2, wdt * .15, 0, -inner)


def smile(img: np.ndarray, lm: np.ndarray, amount: float) -> None:
    """Lift the mouth corners (idle frames only: speech frames paste the generated mouth over this)."""
    if abs(amount) < 0.05:
        return
    wdt = max(np.ptp(lm[48:60, 0]), 8.0)
    for i, sgn in ((MOUTH_L, 1), (MOUTH_R, -1)):
        _bump(img, lm[i], wdt * .22, wdt * .18, sgn * amount * .25, -amount)
