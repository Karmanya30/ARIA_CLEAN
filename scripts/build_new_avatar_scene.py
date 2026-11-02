r"""Builds the New ARIA Avatar's clips on the ORIGINAL avatar's scene (the bright office, plants, shelves, desk, window), with the moving
presenter from the supplied video placed over the old avatar's seated figure. Run with the MuseTalk Python environment:

    set MUSETALK_DIR=E:\musetalk\MuseTalk
    E:\musetalk\env\python.exe scripts\build_new_avatar_scene.py --test        (one frame, to look at)
    E:\musetalk\env\python.exe scripts\build_new_avatar_scene.py               (all clips)

How: the person is cut out of every video frame (MuseTalk's face-parsing network), moved and scaled so her face lands on the old avatar's face (face boxes from MuseTalk's own detector), and
composited with a soft edge over a 16:9 crop of the old photo. Her clothes were already the same (navy blazer, white blouse).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile

import cv2
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MT = os.environ.get("MUSETALK_DIR", r"E:\musetalk\MuseTalk")
OUT_W, OUT_H = 1280, 720
AV = os.path.join(ROOT, "interface", "avatar")
SRC_VIDEO = os.environ.get("ARIA_AVATAR_VIDEO") or os.path.join(ROOT, ".audit", "src.mp4")  # the supplied video (copy it here once so the path has no spaces)
OLD = os.path.join(AV, "office-wide-glasses.webp")


def face_boxes(images: list[np.ndarray]) -> list[tuple[float, float, float, float]]:
    """Face box per image, from MuseTalk's own landmark detector (the same one the lip-sync uses)."""
    cwd = os.getcwd()
    os.chdir(MT)
    sys.path.insert(0, MT)
    try:
        from musetalk.utils.preprocessing import get_landmark_and_bbox

        tmp = tempfile.mkdtemp()
        paths = []
        for i, im in enumerate(images):
            p = os.path.join(tmp, f"{i:06d}.png")
            cv2.imwrite(p, im)
            paths.append(p)
        coords, _ = get_landmark_and_bbox(paths, 0)
        return [tuple(float(v) for v in c) for c in coords]
    finally:
        os.chdir(cwd)


class Matte:
    """The presenter's silhouette from MuseTalk's face-parsing network (hair, skin, neck, clothes = person), run on the central square of
    the frame, where her head and shoulders are. The edges that cut across her shoulders fade out, so the old photo's own
    shoulders (same blazer) take over there."""

    def __init__(self):
        import torch

        cwd = os.getcwd()
        os.chdir(MT)
        sys.path.insert(0, MT)
        try:
            from musetalk.utils.face_parsing import FaceParsing

            self.fp = FaceParsing()
        finally:
            os.chdir(cwd)
        self.torch = torch

    def __call__(self, bgr: np.ndarray) -> np.ndarray:
        from PIL import Image

        h, w = bgr.shape[:2]
        side = min(h, w)
        x0 = (w - side) // 2
        crop = Image.fromarray(cv2.cvtColor(bgr[:, x0:x0 + side], cv2.COLOR_BGR2RGB)).resize((512, 512), Image.BILINEAR)
        with self.torch.no_grad():
            t = self.fp.preprocess(crop)[None].cuda() if self.torch.cuda.is_available() else self.fp.preprocess(crop)[None]
            labels = self.fp.net(t)[0].squeeze(0).cpu().numpy().argmax(0)
        person = ((labels != 0) & (labels != 18)).astype(np.float32)  # 18 = hat; 0 = background
        person = cv2.morphologyEx(person, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
        person = cv2.resize(person, (side, side), interpolation=cv2.INTER_LINEAR)
        ramp = np.ones((side, side), np.float32)
        f = max(8, int(0.10 * side))
        for i in range(f):
            v = (i + 1) / f
            ramp[:, i] = np.minimum(ramp[:, i], v); ramp[:, side - 1 - i] = np.minimum(ramp[:, side - 1 - i], v); ramp[side - 1 - i, :] = np.minimum(ramp[side - 1 - i, :], v)
        full = np.zeros((h, w), np.float32)
        full[:, x0:x0 + side] = person * ramp
        return full


def old_scene() -> tuple[np.ndarray, tuple[float, float, float, float]]:
    """A 16:9 crop of the old photo around her, at the output size, and her face box in that crop."""
    from PIL import Image

    im = cv2.cvtColor(np.array(Image.open(OLD).convert("RGB")), cv2.COLOR_RGB2BGR)
    box = face_boxes([im])[0]
    cx = (box[0] + box[2]) / 2
    ch = im.shape[0]
    cw = ch * 16 / 9
    x0 = int(round(min(max(cx - cw / 2, 0), im.shape[1] - cw)))
    crop = im[:, x0:x0 + int(cw)]
    k = OUT_W / crop.shape[1]
    scene = cv2.resize(crop, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
    sbox = tuple((v - (x0 if i % 2 == 0 else 0)) * k for i, v in enumerate(box))
    return scene, sbox


def video_frames(start: float, end: float, fps: int = 25) -> list[np.ndarray]:
    tmp = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(end - start), "-i", SRC_VIDEO, "-vf", f"fps={fps}",
                    os.path.join(tmp, "%06d.png")], check=True)
    return [cv2.imread(os.path.join(tmp, f)) for f in sorted(os.listdir(tmp))]


def compose(frames: list[np.ndarray], scene, sbox, matte: Matte, ref_box) -> list[np.ndarray]:
    """Moves/scales every frame so the presenter's (reference) face sits on the old avatar's face, then blends with a soft matte."""
    out = []
    s = ((sbox[2] - sbox[0]) / (ref_box[2] - ref_box[0]) + (sbox[3] - sbox[1]) / (ref_box[3] - ref_box[1])) / 2
    tx = (sbox[0] + sbox[2]) / 2 - s * (ref_box[0] + ref_box[2]) / 2
    ty = (sbox[1] + sbox[3]) / 2 - s * (ref_box[1] + ref_box[3]) / 2
    M = np.array([[s, 0, tx], [0, s, ty]], np.float32)
    for fr in frames:
        a = cv2.GaussianBlur(matte(fr), (0, 0), 2.5)  # soft edge
        wf = cv2.warpAffine(fr, M, (OUT_W, OUT_H), flags=cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        wa = cv2.warpAffine(a, M, (OUT_W, OUT_H), flags=cv2.INTER_LINEAR, borderValue=0)[..., None]
        out.append((wf.astype(np.float32) * wa + scene.astype(np.float32) * (1 - wa)).astype(np.uint8))
    return out


def write_clip(frames: list[np.ndarray], name: str, boomerang: bool, crf: int) -> None:
    """Frames -> H.264 at 25 fps; a boomerang plays forward then backward (seamless loop; frame index = time * 25)."""
    tmp = tempfile.mkdtemp()
    for i, f in enumerate(frames):
        cv2.imwrite(os.path.join(tmp, f"{i:06d}.png"), f)
    out = os.path.join(AV, f"presenter-{name}.mp4")
    enc = ["-c:v", "libx264", "-preset", "slow", "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-an"]
    src = ["-framerate", "25", "-i", os.path.join(tmp, "%06d.png")]
    if boomerang:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *src, "-filter_complex", "[0:v]split[x][y];[y]reverse[r];[x][r]concat=n=2:v=1[o]", "-map", "[o]", *enc, out], check=True)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-y", *src, *enc, out], check=True)
    print("wrote", out, len(frames), "frames" + (" x2 (boomerang)" if boomerang else ""))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()
    scene, sbox = old_scene()
    matte = Matte()
    calm = video_frames(10.6, 12.9)
    boxes = face_boxes(calm)
    ref = tuple(float(np.median([b[i] for b in boxes])) for i in range(4))
    print("old face box", [round(v) for v in sbox], "video face box", [round(v) for v in ref])
    if a.test:
        res = compose([calm[len(calm) // 2]], scene, sbox, matte, ref)[0]
        cv2.imwrite(os.path.join(ROOT, ".audit", "scene_test.png"), res)
        print("wrote .audit/scene_test.png")
        sys.exit(0)
    calm_c = compose(calm, scene, sbox, matte, ref)
    write_clip(calm_c, "lipsync", boomerang=False, crf=17)   # the GPU server turns it into a back-and-forth loop itself
    write_clip(calm_c, "idle", boomerang=True, crf=21)       # the same frames, forward then backward: what the page shows when nothing happens
    listen_c = compose(video_frames(14.4, 17.0), scene, sbox, matte, ref)
    write_clip(listen_c, "listen", boomerang=True, crf=22)   # attentive: a smile and a slight head tilt, only while she listens to the client
