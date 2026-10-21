"""Backend contract + the on-disk replica cache format shared by all backends."""
from __future__ import annotations

import pickle
import threading
from pathlib import Path
from typing import Iterator

import numpy as np

from .compositor import ReplicaData


class GpuOom(RuntimeError):
    """Raised by a backend when the GPU ran out of memory even after retrying with smaller batches."""


class Backend:
    name = "base"
    batch = 8
    vae_mode = "n/a"

    def load(self) -> None:            # heavy: models to GPU + warm-up
        raise NotImplementedError

    def prepare(self, src: Path, dest: Path) -> dict:   # detect face, crop, latents, masks -> dest/prep.pkl ; returns meta
        raise NotImplementedError

    def lipsync(self, rep: ReplicaData, wav16: np.ndarray, fps: int, start_idx: int, cancel: threading.Event) -> Iterator[np.ndarray]:
        """Yield (n,256,256,3) BGR uint8 face batches for int(len(wav16)/16000*fps) mouth frames, as soon as each is ready."""
        raise NotImplementedError

    def info(self) -> dict:
        return {"gpu": None, "vram_used_mb": 0}

    def downgrade(self) -> str | None:
        """Make generation cheaper after an out-of-memory error; returns a description, or None if nothing is left to cut."""
        return None

    # ---- shared cache format
    @staticmethod
    def save(dest: Path, rep: ReplicaData) -> None:
        with open(dest / "prep.pkl", "wb") as f:
            pickle.dump(rep, f, protocol=pickle.HIGHEST_PROTOCOL)

    def load_replica(self, d: Path, rid: str) -> ReplicaData:
        with open(d / "prep.pkl", "rb") as f:
            rep = pickle.load(f)
        rep.id = rid
        return rep
