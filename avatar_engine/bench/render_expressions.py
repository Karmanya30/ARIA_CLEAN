"""CPU-only visual check of blink/emotion/background rendering on the default replica -> contact sheets (no GPU, no server)."""
import sys, pickle
sys.path.insert(0, r"E:\ARIA")
import cv2, numpy as np
from avatar_engine.compositor import Scaled, StageOpts, render
from avatar_engine.motion import Pose, PRESETS, IdleMotion
rep = pickle.load(open(r"E:\ARIA\data\avatar\replicas\default\prep.pkl", "rb"))
dec = lambda b: cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_UNCHANGED)
sc = Scaled(rep, StageOpts(400, 400, "face", "original"))
def lab(img, t): img = img.copy(); cv2.putText(img, t, (8, 24), 0, .7, (0, 255, 0), 2); return img
row1 = [lab(dec(render(sc, 0, Pose(blink=b))), f"blink {b}") for b in (0, .5, .8, 1.0)]
row2 = []
for name, p in PRESETS.items():
    row2.append(lab(dec(render(sc, 0, Pose(brow=p["brow"], inner=p["inner"], smile=p["smile"], rot=p["tilt"]))), name))
cv2.imwrite(r"E:\avatar_bench\expr_blink.jpg", np.hstack(row1)); cv2.imwrite(r"E:\avatar_bench\expr_emotions.jpg", np.hstack(row2))
bgs = []
for bg in ("blur", "#0b1d3a", "transparent"):
    s2 = Scaled(rep, StageOpts(400, 400, "bust", bg)); im = dec(render(s2, 0, Pose()))
    if im.shape[2] == 4:
        a = im[..., 3:] / 255.0; chk = ((np.indices(im.shape[:2]).sum(0) // 20) % 2 * 60 + 100).astype(np.uint8)[..., None].repeat(3, 2)
        im = (im[..., :3] * a + chk * (1 - a)).astype(np.uint8)
    bgs.append(lab(im, bg))
cv2.imwrite(r"E:\avatar_bench\expr_bg.jpg", np.hstack(bgs))
print("ok", rep.lm is not None, rep.matte is not None)
