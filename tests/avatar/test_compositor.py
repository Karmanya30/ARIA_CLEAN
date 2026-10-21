import cv2
import numpy as np
import pytest

from avatar_engine import expressions as ex
from avatar_engine.compositor import Scaled, StageOpts, pingpong, render
from avatar_engine.motion import PRESETS, IdleMotion, Pose


def _landmarks(rep):
    x1, y1, x2, y2 = rep.coords[0]
    cx, w, h = (x1 + x2) / 2, x2 - x1, y2 - y1
    lm = np.zeros((68, 2), np.float32)
    for sl, ox in ((ex.R_EYE, -.25), (ex.L_EYE, .25)):
        ang = np.linspace(0, 2 * np.pi, 6, endpoint=False)
        lm[sl] = np.c_[cx + ox * w + 0.08 * w * np.cos(ang), y1 + .3 * h + 0.025 * w * np.sin(ang)]
    lm[ex.R_BROW] = np.c_[np.linspace(cx - .35 * w, cx - .1 * w, 5), np.full(5, y1 + .2 * h)]
    lm[ex.L_BROW] = np.c_[np.linspace(cx + .1 * w, cx + .35 * w, 5), np.full(5, y1 + .2 * h)]
    t = np.linspace(0, 6.28, 12)
    lm[48:60] = np.c_[cx + .2 * w * np.cos(t), y1 + .75 * h + 5 * np.sin(t)]
    return lm


def test_pingpong():
    assert [pingpong(i, 4) for i in range(8)] == [0, 1, 2, 3, 2, 1, 0, 1]
    assert pingpong(5, 1) == 0


@pytest.mark.parametrize("bg", ["original", "blur", "#112233", "transparent"])
@pytest.mark.parametrize("framing", ["bust", "face", "full"])
def test_render_all_options(engine, bg, framing):
    rep = engine.get_replica("default")
    rep.matte = np.full(rep.frames[0].shape[:2], 0.5, np.float32)
    rep.lm = _landmarks(rep)
    sc = Scaled(rep, StageOpts(320, 400, framing, bg))
    data = render(sc, 0, Pose(blink=1, gaze_x=1, brow=2, inner=2, smile=2, rot=2), np.zeros((256, 256, 3), np.uint8), 1.0)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    assert img.shape[:2] == (400, 320)
    assert img.shape[2] == (4 if bg == "transparent" else 3)


def test_blink_changes_only_the_eye_region(engine):
    rep = engine.get_replica("default")
    lm = _landmarks(rep)
    base = rep.frames[0].copy()
    a = base.copy()
    ex.eye(a, lm[ex.R_EYE], 0.0)
    assert np.array_equal(a, base)                       # open eye, no gaze shift: identity
    b = base.copy()
    ex.eye(b, lm[ex.R_EYE], 1.0)
    assert (b != base).any()
    x1, y1 = lm[ex.R_EYE].min(0).astype(int)
    x2, y2 = lm[ex.R_EYE].max(0).astype(int)
    far = np.ones(base.shape[:2], bool)
    far[max(0, y1 - 200):y2 + 100, max(0, x1 - 100):x2 + 100] = False
    assert np.array_equal(b[far], base[far])


def test_mouth_patch_only_changes_the_face_region(engine):
    rep = engine.get_replica("default")
    sc = Scaled(rep, StageOpts(512, 512))
    neutral = render(sc, 0, Pose(), None, 0)
    patch = render(sc, 0, Pose(), np.full((256, 256, 3), 255, np.uint8), 1.0)
    a, b = (cv2.imdecode(np.frombuffer(x, np.uint8), 1).astype(int) for x in (neutral, patch))
    d = np.abs(a - b).sum(2)
    assert d.max() > 100 and d[:20].max() < 30           # the top of the frame is untouched


def test_idle_motion_blinks_and_stays_small():
    m = IdleMotion(seed=1)
    poses = [m.step(i / 25, 1 / 25) for i in range(25 * 20)]
    blinks = sum(1 for a, b in zip(poses, poses[1:]) if a.blink < .5 <= b.blink)
    assert 3 <= blinks <= 12                              # about one blink every 3-4 s
    assert max(abs(p.dx) for p in poses) < 6 and max(abs(p.rot) for p in poses) < 3
    assert 0.0 <= min(p.blink for p in poses) and max(p.blink for p in poses) <= 1.0


def test_emotion_presets_reach_their_targets():
    m = IdleMotion(seed=2)
    for name, p in PRESETS.items():
        m.set_mood(name)
        for i in range(25 * 4):
            m.step(i / 25, 1 / 25)
        assert abs(m.cur["brow"] - p["brow"]) < 0.05 and abs(m.cur["smile"] - p["smile"]) < 0.05
