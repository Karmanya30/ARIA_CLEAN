"""No-GPU stand-in backend for tests and for running the protocol without MuseTalk: guesses a centred face box and draws a
mouth whose opening follows the audio energy. `delay` seconds per frame simulates generation cost."""
from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

from .backend_base import Backend
from .compositor import ReplicaData


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, delay: float = 0.0, batch: int = 8):
        self.delay, self.batch = delay, batch
        self.calls = 0

    def load(self) -> None:
        pass

    def prepare(self, src: Path, dest: Path) -> dict:
        img = cv2.imread(str(src))
        if img is None:
            cap = cv2.VideoCapture(str(src))
            ok, img = cap.read()
            if not ok:
                raise RuntimeError("cannot read image or video")
        H, W = img.shape[:2]
        fw = int(W * .4)
        box = (W // 2 - fw // 2, int(H * .25), W // 2 + fw // 2, int(H * .25) + int(fw * 1.2))
        cs = int(fw * 1.5) // 2 * 2
        cx, cy = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
        mb = (max(0, cx - cs // 2), max(0, cy - cs // 2), min(W, cx + cs // 2), min(H, cy + cs // 2))
        a = np.zeros((mb[3] - mb[1], mb[2] - mb[0]), np.float32)
        a[a.shape[0] // 2:] = 1
        a = cv2.GaussianBlur(a, (0, 0), 8)
        crop = cv2.resize(img[box[1]:box[3], box[0]:box[2]], (256, 256))
        rep = ReplicaData(id="", kind="photo", frames=[img], coords=[box], mask_boxes=[mb], alphas=[a], crops=[crop])
        self.save(dest, rep)
        return {"face_box": list(box), "size": [W, H], "frames": 1}

    def lipsync(self, rep, wav16, fps, start_idx, cancel):
        n = int(len(wav16) / 16000 * fps)
        self.calls += 1
        for b0 in range(0, n, self.batch):
            if cancel.is_set():
                return
            m = min(self.batch, n - b0)
            if self.delay:
                time.sleep(self.delay * m)
            out = np.repeat(rep.crops[0][None], m, 0).copy()
            for i in range(m):
                s = wav16[int((b0 + i) / fps * 16000):int((b0 + i + 1) / fps * 16000)]
                open_ = float(np.sqrt(np.mean(s ** 2))) if len(s) else 0.0
                cv2.ellipse(out[i], (128, 200), (40, 3 + int(min(open_ * 200, 30))), 0, 0, 360, (30, 30, 120), -1)
            yield out
