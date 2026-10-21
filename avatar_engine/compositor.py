"""Frame compositor (CPU, cv2/numpy only): replica photo/video frames + generated mouth patch + idle pose -> encoded image.
Everything happens at output resolution (the photo is pre-scaled once per stage setting), so a frame costs a few ms."""
from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import expressions as ex
from .motion import Pose

FRAMINGS = {"bust": 2.6, "face": 1.7, "full": 0.0}   # window width as a multiple of the face width (full = whole photo)


@dataclass
class ReplicaData:
    id: str
    kind: str                      # photo | video
    frames: list                   # BGR uint8, full size
    coords: list                   # face box (x1,y1,x2,y2) per frame
    mask_boxes: list               # paste region (xs,ys,xe,ye) per frame
    alphas: list                   # float32 HxWx1 blend masks for the paste region
    crops: list = field(default_factory=list)   # 256x256 BGR face crops (backend input)
    lm: np.ndarray | None = None   # 68 face landmarks of frame 0 (photos only)
    matte: np.ndarray | None = None  # float32 HxW person matte of frame 0 (photos only)
    extra: dict = field(default_factory=dict)    # backend data (latents ...)


def pingpong(i: int, n: int) -> int:
    if n <= 1:
        return 0
    p = i % (2 * n - 2)
    return p if p < n else 2 * n - 2 - p


@dataclass
class StageOpts:
    w: int = 512
    h: int = 512
    framing: str = "bust"
    bg: str = "original"           # original | blur | transparent | #rrggbb
    quality: int = 85

    def key(self):
        return (self.w, self.h, self.framing, self.bg)


class Scaled:
    """A replica pre-scaled for one stage setting."""

    def __init__(self, rep: ReplicaData, o: StageOpts):
        self.rep, self.o = rep, o
        x1, y1, x2, y2 = rep.coords[0]
        H, W = rep.frames[0].shape[:2]
        fw = x2 - x1
        ww = W if FRAMINGS.get(o.framing, 2.6) == 0 else min(W * 1.0, fw * FRAMINGS.get(o.framing, 2.6))
        wh = ww * o.h / o.w
        if wh > H:
            wh, ww = H, H * o.w / o.h
        cx = min(max((x1 + x2) / 2, ww / 2), W - ww / 2)
        cy = (y1 + y2) / 2 + (0.18 * wh if o.framing != "full" else 0)
        cy = min(max(cy, wh / 2), H - wh / 2)
        self.S = S = o.w / ww
        self.c = (cx * S, cy * S)
        interp = cv2.INTER_AREA if S < 1 else cv2.INTER_CUBIC
        self.frames = [cv2.resize(f, None, fx=S, fy=S, interpolation=interp) for f in rep.frames]
        sc = lambda b: [int(round(v * S)) for v in b]
        self.coords = [sc(c) for c in rep.coords]
        self.boxes = [sc(b) for b in rep.mask_boxes]
        self.alphas = []
        for b, a in zip(self.boxes, rep.alphas):
            self.alphas.append(cv2.resize(a, (b[2] - b[0], b[3] - b[1]), interpolation=cv2.INTER_AREA)[..., None])
        self.lm = rep.lm * S if rep.lm is not None else None
        self.matte = self.bgimg = None
        if rep.matte is not None and o.bg != "original":
            self.matte = cv2.resize(rep.matte, None, fx=S, fy=S, interpolation=cv2.INTER_AREA)
            if o.bg == "blur":
                self.bgimg = cv2.GaussianBlur(self.frames[0], (0, 0), max(6, o.w / 40))
            elif o.bg.startswith("#") and len(o.bg) == 7:
                r, g, b = (int(o.bg[i:i + 2], 16) for i in (1, 3, 5))
                self.bgimg = np.full_like(self.frames[0], (b, g, r))
        self.matte_out = None   # warped per frame

    @property
    def transparent(self) -> bool:
        return self.matte is not None and self.o.bg == "transparent"


def _paste(base: np.ndarray, sc: Scaled, k: int, face: np.ndarray, gain: float) -> None:
    x1, y1, x2, y2 = sc.coords[k]
    xs, ys, xe, ye = sc.boxes[k]
    H, W = base.shape[:2]
    if xs < 0 or ys < 0 or xe > W or ye > H or x2 <= x1 or y2 <= y1:
        return
    roi = base[ys:ye, xs:xe]
    patch = roi.copy()
    patch[y1 - ys:y2 - ys, x1 - xs:x2 - xs] = cv2.resize(face, (x2 - x1, y2 - y1), interpolation=cv2.INTER_AREA if x2 - x1 < 256 else cv2.INTER_CUBIC)
    a = sc.alphas[k] * gain
    roi[:] = (patch * a + roi * (1 - a)).astype(np.uint8)


def render(sc: Scaled, k: int, pose: Pose, face: np.ndarray | None = None, gain: float = 1.0) -> bytes:
    o = sc.o
    base = sc.frames[k].copy()
    px = o.w / 512.0
    if sc.lm is not None:
        lm = sc.lm
        ex.smile(base, lm, pose.smile * px)
        ex.brows(base, lm, pose.brow * px, pose.inner * px)
        g = (pose.gaze_x * px, pose.gaze_y * px)
        ex.eye(base, lm[ex.R_EYE], pose.blink, g)
        ex.eye(base, lm[ex.L_EYE], pose.blink, g)
    if face is not None and gain > 0.001:
        _paste(base, sc, k, face, min(gain, 1.0))
    cx, cy = sc.c
    M = cv2.getRotationMatrix2D((cx, cy), pose.rot, pose.scale)
    M[0, 2] += o.w / 2 - cx + pose.dx * px
    M[1, 2] += o.h / 2 - cy + pose.dy * px
    out = cv2.warpAffine(base, M, (o.w, o.h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    if sc.matte is not None and (sc.bgimg is not None or sc.transparent):
        m = cv2.warpAffine(sc.matte, M, (o.w, o.h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        if sc.transparent:
            out = np.dstack([out, (m * 255).astype(np.uint8)])
            return cv2.imencode(".webp", out, [cv2.IMWRITE_WEBP_QUALITY, o.quality])[1].tobytes()
        bgw = cv2.warpAffine(sc.bgimg, M, (o.w, o.h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        m = m[..., None]
        out = (out * m + bgw * (1 - m)).astype(np.uint8)
    return cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, o.quality])[1].tobytes()
