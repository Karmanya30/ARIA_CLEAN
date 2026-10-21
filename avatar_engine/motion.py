"""Natural idle motion and emotion presets: a time-driven generator of head pose, blink and gaze (no GPU).
px values are for a 512 px wide output (the compositor scales them). Honest limit: presets change head pose, brows and
smile only; the generated mouth during speech is not affected (MuseTalk has no style conditioning)."""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

PRESETS = {
    "neutral":   dict(sway=1.0, tilt=0.0, nod=0.0, brow=0.0, inner=0.0, smile=0.0, blink=3.8),
    "warm":      dict(sway=1.1, tilt=1.6, nod=0.0, brow=3.0, inner=0.0, smile=6.0, blink=3.5),
    "serious":   dict(sway=0.55, tilt=0.0, nod=0.8, brow=-4.0, inner=0.0, smile=-1.5, blink=5.0),
    "concerned": dict(sway=0.7, tilt=2.6, nod=0.5, brow=0.0, inner=5.5, smile=-1.5, blink=4.2),
    "upbeat":    dict(sway=1.5, tilt=-1.2, nod=-0.4, brow=5.0, inner=0.0, smile=8.0, blink=3.0),
}
LISTENING = dict(sway=0.8, tilt=2.0, nod=-0.4, brow=1.0, inner=0.8, smile=0.8, blink=4.0)


@dataclass
class Pose:
    dx: float = 0.0
    dy: float = 0.0
    rot: float = 0.0      # degrees
    scale: float = 1.0
    blink: float = 0.0    # 0 open .. 1 closed
    gaze_x: float = 0.0
    gaze_y: float = 0.0
    brow: float = 0.0
    inner: float = 0.0
    smile: float = 0.0


class IdleMotion:
    def __init__(self, seed: int | None = None):
        self.r = random.Random(seed)
        self.ph = [self.r.uniform(0, 6.28) for _ in range(6)]
        self.cur = dict(PRESETS["neutral"])
        self.target = dict(PRESETS["neutral"])
        self.next_blink = 1.2
        self.blink_t0: float | None = None
        self.blink_len = 0.17
        self.again = False
        self.next_gaze = 1.5
        self.gaze_from = (0.0, 0.0)
        self.gaze_to = (0.0, 0.0)
        self.gaze_t0 = 0.0
        self.energy = 0.0

    def set_mood(self, name: str, listening: bool = False) -> None:
        self.target = dict(LISTENING if listening else PRESETS.get(name, PRESETS["neutral"]))

    def _blink(self, t: float) -> float:
        if self.blink_t0 is None and t >= self.next_blink:
            self.blink_t0, self.blink_len = t, self.r.uniform(0.14, 0.21)
            self.again = self.r.random() < 0.12
        if self.blink_t0 is None:
            return 0.0
        k = (t - self.blink_t0) / self.blink_len
        if k >= 1:
            if self.again:       # double blink
                self.again, self.blink_t0 = False, t + 0.08
                return 0.0
            self.blink_t0 = None
            self.next_blink = t + self.r.uniform(0.6, 1.4) * self.cur["blink"]
            return 0.0
        if k < 0:
            return 0.0
        return math.sin(math.pi * (k / 0.4) / 2) if k < 0.4 else math.cos(math.pi * (k - .4) / .6 / 2) ** 2

    def step(self, t: float, dt: float, speaking: bool = False, energy: float = 0.0) -> Pose:
        a = 1 - math.exp(-dt / 0.35)                      # ease toward the preset (~0.35 s)
        for k, v in self.target.items():
            self.cur[k] += (v - self.cur[k]) * a
        c = self.cur
        self.energy += (energy - self.energy) * (1 - math.exp(-dt / 0.08))
        s, ph = c["sway"], self.ph
        amp = s * (1.5 if speaking else 1.0)
        p = Pose(
            dx=amp * (1.6 * math.sin(.55 * t + ph[0]) + .8 * math.sin(1.3 * t + ph[1])),
            dy=amp * (1.2 * math.sin(.43 * t + ph[2]) + .6 * math.sin(1.1 * t + ph[3])) + c["nod"] * 2 + self.energy * 5.0 * s,
            rot=c["tilt"] + amp * (0.45 * math.sin(.37 * t + ph[4]) + .2 * math.sin(.91 * t + ph[5])) + self.energy * 0.8 * math.sin(2.2 * t),
            scale=1.0 + 0.004 * math.sin(.52 * t) * s + 0.01 * self.energy,   # breathing + emphasis
            blink=self._blink(t),
            brow=c["brow"] + (self.energy * 1.5 if speaking else 0.0), inner=c["inner"], smile=c["smile"],
        )
        if t >= self.next_gaze:                           # small eye saccades
            self.gaze_from = self.gaze_to
            self.gaze_to = (self.r.uniform(-1.6, 1.6), self.r.uniform(-.8, .8))
            self.gaze_t0, self.next_gaze = t, t + self.r.uniform(1.2, 3.5)
        k = min((t - self.gaze_t0) / 0.12, 1.0)
        p.gaze_x = self.gaze_from[0] + (self.gaze_to[0] - self.gaze_from[0]) * k
        p.gaze_y = self.gaze_from[1] + (self.gaze_to[1] - self.gaze_from[1]) * k
        return p
