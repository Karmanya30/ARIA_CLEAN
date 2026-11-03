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
OUT_W, OUT_H = 1440, 616   # the old avatar photo's own proportions (2.34:1), so the page frames it exactly like the old avatar and the whole office shows
AV = os.path.join(ROOT, "interface", "avatar")
SRC_VIDEO = os.environ.get("ARIA_AVATAR_VIDEO") or os.path.join(ROOT, ".audit", "src.mp4")  # the supplied video (copy it here once so the path has no spaces)
SCALE_UP = 1.3     # her size relative to the old figure, so her silhouette covers it
FACE_CY = 245      # where her face centre sits (y), low enough that her body reaches the desk, which hides its lower end
SRC_H = 480        # height of the supplied video (848 x 480)
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
    """Person / skin masks from MuseTalk's face-parsing network (hair, skin, neck, clothes = person). It runs on a square window with
    replicated borders, so shoulders at the edge of the frame are not cut off."""

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

    def labels(self, bgr: np.ndarray, x0: int, y0: int, side: int) -> np.ndarray:
        """Parsing label per pixel (0 background, 1 skin, 14 neck, 16 clothes, 17 hair ...) for the whole image, from the window at x0,y0."""
        from PIL import Image

        h, w = bgr.shape[:2]
        big = cv2.copyMakeBorder(bgr, side, side, side, side, cv2.BORDER_REPLICATE)
        crop = Image.fromarray(cv2.cvtColor(big[y0 + side:y0 + 2 * side, x0 + side:x0 + 2 * side], cv2.COLOR_BGR2RGB)).resize((512, 512), Image.BILINEAR)
        with self.torch.no_grad():
            t = self.fp.preprocess(crop)[None].cuda() if self.torch.cuda.is_available() else self.fp.preprocess(crop)[None]
            lab = self.fp.net(t)[0].squeeze(0).cpu().numpy().argmax(0).astype(np.uint8)
        lab = cv2.resize(lab, (side, side), interpolation=cv2.INTER_NEAREST)
        out = np.zeros((h, w), np.uint8)
        xs, ys, xe, ye = max(x0, 0), max(y0, 0), min(x0 + side, w), min(y0 + side, h)
        out[ys:ye, xs:xe] = lab[ys - y0:ye - y0, xs - x0:xe - x0]
        return out

    def video_labels(self, bgr: np.ndarray) -> np.ndarray:  # the presenter: a square window as wide as her shoulders need
        h, w = bgr.shape[:2]
        side = 960
        return self.labels(bgr, (w - side) // 2, (h - side) // 2, side)

    def __call__(self, bgr: np.ndarray) -> np.ndarray:
        lab = self.video_labels(bgr)
        person = ((lab != 0) & (lab != 18)).astype(np.uint8)  # 18 = hat; 0 = background
        return cv2.morphologyEx(person, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)).astype(np.float32)


# Her shoulders in the supplied video (848 x 480): the parser does not recognise a dark navy blazer against a dark office, so the body is cut out
# once per clip with GrabCut inside this outline (she barely moves her shoulders), and the head and hair come from the parser frame by frame.
BODY_POLY = np.array([[262, 335], [215, 372], [183, 430], [178, 480], [665, 480], [662, 430], [632, 380], [575, 337]], np.int32)
BODY_TOP = 300  # the body mask only applies from here down (above it the per-frame parser mask draws the head and hair)


def body_mask(frames: list[np.ndarray], matte: Matte) -> np.ndarray:
    med = np.median(np.stack(frames), axis=0).astype(np.uint8)
    h, w = med.shape[:2]
    person = ((matte.video_labels(med) != 0) & (matte.video_labels(med) != 18)).astype(np.uint8)
    core = np.zeros((h, w), np.uint8)
    cv2.fillPoly(core, [BODY_POLY], 1)
    gm = np.full((h, w), cv2.GC_BGD, np.uint8)
    gm[cv2.dilate(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (45, 45))) > 0] = cv2.GC_PR_BGD
    gm[core > 0] = cv2.GC_PR_FGD
    gm[cv2.erode(core, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41))) > 0] = cv2.GC_FGD
    gm[person > 0] = cv2.GC_FGD
    cv2.grabCut(med, gm, None, np.zeros((1, 65)), np.zeros((1, 65)), 6, cv2.GC_INIT_WITH_MASK)
    body = ((gm == cv2.GC_FGD) | (gm == cv2.GC_PR_FGD)).astype(np.float32)
    body[:BODY_TOP] = 0
    return body


def old_scene(matte: Matte) -> tuple[np.ndarray, tuple[float, float, float, float], np.ndarray]:
    """The whole old photo at the output size, her face box in it, and the old figure's silhouette mask."""
    from PIL import Image

    im = cv2.cvtColor(np.array(Image.open(OLD).convert("RGB")), cv2.COLOR_RGB2BGR)
    box = face_boxes([im])[0]
    kx, ky = OUT_W / im.shape[1], OUT_H / im.shape[0]
    scene = cv2.resize(im, (OUT_W, OUT_H), interpolation=cv2.INTER_AREA)
    lab = matte.labels(scene, 325, -92, 800)
    person = ((lab != 0) & (lab != 18)).astype(np.uint8)
    person = cv2.morphologyEx(person, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (41, 41)))
    hsv = cv2.cvtColor(scene, cv2.COLOR_BGR2HSV)  # dark navy sleeve edges that the parser calls background
    navy = ((hsv[..., 2] < 90) & (hsv[..., 0] > 100) & (hsv[..., 0] < 135)).astype(np.uint8)
    person = np.maximum(person, cv2.dilate(person, np.ones((31, 31), np.uint8)) & navy)
    mask = cv2.dilate(person, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (49, 49)))  # generous: every trace of the old figure must go
    return scene, (box[0] * kx, box[1] * ky, box[2] * kx, box[3] * ky), mask


DESK_EDGE = (420, 498, 0.046)  # the desk's back edge: x0, y at x0, slope


def make_plate(scene: np.ndarray, old_mask: np.ndarray) -> np.ndarray:
    """The office with the old figure removed completely: the wall, chair and window behind her are inpainted, and the desk under her hands is
    rebuilt row by row from the clean desk on both sides. The new presenter is drawn over this, so only slivers beside her show."""
    hole = cv2.dilate((old_mask > 0).astype(np.uint8), np.ones((5, 5), np.uint8))
    desk = scene.copy()
    x0, y0, k = DESK_EDGE
    xl, xr = 440, 1010  # clean desk on both sides of the old figure
    xs = np.arange(xl, xr)
    for dy in range(-12, OUT_H - y0 - int(k * (xr - x0)) - 1):  # rows measured from the desk's back edge
        yl, yr = int(y0 + k * (xl - x0)) + dy, int(y0 + k * (xr - x0)) + dy
        if yr >= OUT_H:
            break
        left, right = scene[yl, xl - 8:xl].mean(0), scene[yr, xr:xr + 8].mean(0)
        t = np.clip((xs - xl) / 140, 0, 1)  # the desk is lit bright at the far left and plain wood from here on: change over the first 140 px
        t = (t * t * (3 - 2 * t))[:, None]
        yy = (y0 + k * (xs - x0)).astype(int) + dy
        ok = yy < OUT_H
        desk[yy[ok], xs[ok]] = (left * (1 - t) + right * t)[ok]
    deskzone = np.zeros((OUT_H, OUT_W), np.uint8)
    cv2.fillPoly(deskzone, [np.array([[xl, y0 - 6], [xr, int(y0 + k * (xr - x0)) - 6], [xr, OUT_H], [xl, OUT_H]], np.int32)], 1)
    small = cv2.resize(scene, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)  # the desk part is filled too, so it does not bleed up into the wall
    filled = cv2.resize(cv2.inpaint(small, cv2.resize(hole, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_NEAREST), 12, cv2.INPAINT_TELEA), (OUT_W, OUT_H), interpolation=cv2.INTER_CUBIC)
    a = cv2.GaussianBlur(hole.astype(np.float32), (0, 0), 2)[..., None]
    plate = filled * a + scene * (1 - a)
    d = (deskzone > 0) & (hole > 0)
    desk = cv2.GaussianBlur(desk, (0, 0), 1.5)  # the rows were built one by one: smooth the streaks
    plate[d] = desk[d]
    return plate.astype(np.uint8)


def video_frames(start: float, end: float, fps: int = 25) -> list[np.ndarray]:
    tmp = tempfile.mkdtemp()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(start), "-t", str(end - start), "-i", SRC_VIDEO, "-vf", f"fps={fps}",
                    os.path.join(tmp, "%06d.png")], check=True)
    return [cv2.imread(os.path.join(tmp, f)) for f in sorted(os.listdir(tmp))]


def placement(sbox, ref_box) -> np.ndarray:
    """She is placed over the old figure, larger (SCALE_UP) so her head, shoulders and body cover it, her face centred on the old face
    horizontally and at FACE_CY vertically; the desk in front hides the lower end of her body, like a person sitting behind it."""
    s = SCALE_UP * ((sbox[2] - sbox[0]) / (ref_box[2] - ref_box[0]) + (sbox[3] - sbox[1]) / (ref_box[3] - ref_box[1])) / 2
    tx = (sbox[0] + sbox[2]) / 2 - s * (ref_box[0] + ref_box[2]) / 2
    ty = FACE_CY - s * (ref_box[1] + ref_box[3]) / 2
    return np.array([[s, 0, tx], [0, s, ty]], np.float32)


def desk_mask() -> np.ndarray:
    """The part of the desk in front of her: below the desk's back edge (a line across the picture), soft at the edge."""
    d = np.zeros((OUT_H, OUT_W), np.uint8)
    cv2.fillPoly(d, [np.array([[420, 498], [1100, 529], [1100, OUT_H], [420, OUT_H]], np.int32)], 1)
    return cv2.GaussianBlur(d.astype(np.float32), (0, 0), 2.0)[..., None]


def compose(frames: list[np.ndarray], plate, M, matte: Matte, body: np.ndarray, old_mask: np.ndarray | None = None, name: str = "") -> list[np.ndarray]:
    """Cuts her out of every frame (head, hair, neck, clothes) and puts her on the clean office. Nothing of the old figure is kept."""
    out, worst = [], 0
    desk = desk_mask()
    for fr in frames:
        a = cv2.GaussianBlur(np.maximum(matte(fr), body), (0, 0), 1.6)  # soft edge
        wf = cv2.warpAffine(fr, M, (OUT_W, OUT_H), flags=cv2.INTER_AREA if M[0, 0] < 1 else cv2.INTER_LANCZOS4, borderMode=cv2.BORDER_REPLICATE)
        wa = cv2.warpAffine(a, M, (OUT_W, OUT_H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)[..., None]
        img = wf.astype(np.float32) * wa + plate.astype(np.float32) * (1 - wa)
        out.append((img * (1 - desk) + plate.astype(np.float32) * desk).astype(np.uint8))
        if old_mask is not None:  # nothing of the old woman may show when she nods or tilts: no dark hair or blazer where the old figure was and the new one is not
            region = (old_mask > 0) & (wa[..., 0] < 0.05)
            region[490:] = False  # the desk and its shadow
            hsv = cv2.cvtColor(out[-1], cv2.COLOR_BGR2HSV)
            dark = hsv[..., 2] < 80
            n = int((region & dark).sum())  # (skin is not tested here: the wood of the cabinet has the same colour)
            if os.environ.get("ARIA_DEBUG_LEAK") and len(out) == 1:
                v = out[-1].copy(); v[region & dark] = (0, 0, 255); cv2.imwrite(os.path.join(ROOT, ".audit", "leak.png"), v)
            worst = max(worst, n)
            if n > 150:
                raise SystemExit(f"{name}: frame {len(out) - 1} still shows {n} pixels that look like the old figure")
    if old_mask is not None:
        print(f"{name}: old figure not visible in any of {len(frames)} frames (worst frame has {worst} dark pixels where it used to be)")
    return out


def check_no_hands(frames: list[np.ndarray], matte: Matte, ref_box, name: str) -> None:
    """A hand is skin below the neck. Fails if any frame has skin more than a face-height below the chin outside the neckline."""
    fh = ref_box[3] - ref_box[1]
    for i, fr in enumerate(frames):
        lab = matte.video_labels(fr)
        low = lab[int(ref_box[3] + 1.1 * fh):, :]
        skin = int(((low == 1) | (low == 14)).sum())
        if skin > 400:
            raise SystemExit(f"{name}: frame {i} has {skin} skin pixels low in the picture (a hand?)")


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
    matte = Matte()
    photo, sbox, old_mask = old_scene(matte)
    calm = video_frames(10.6, 12.5)   # the supplied video has a thumbs-up gesture from 12.7 s to about 14.8 s: no clip may include it
    boxes = face_boxes(calm)
    ref = tuple(float(np.median([b[i] for b in boxes])) for i in range(4))
    M = placement(sbox, ref)
    print("old face box", [round(v) for v in sbox], "video face box", [round(v) for v in ref], "scale", round(float(M[0, 0]), 3))
    body = body_mask(calm, matte)
    mid = calm[len(calm) // 2]
    cover = cv2.warpAffine(np.maximum(matte(mid), body), M, (OUT_W, OUT_H), flags=cv2.INTER_LINEAR)
    plate = make_plate(photo, old_mask)
    cv2.imwrite(os.path.join(ROOT, ".audit", "plate.png"), plate)
    try:
        found = face_boxes([plate])[0] != (0.0, 0.0, 0.0, 0.0)
    except ZeroDivisionError:  # MuseTalk's detector divides by the number of faces it found
        found = False
    if found:
        raise SystemExit("the clean office still has a face in it (the old figure)")
    print("the clean office has no face in it")
    if a.test:
        res = compose([mid], plate, M, matte, body)[0]
        cv2.imwrite(os.path.join(ROOT, ".audit", "scene_test.png"), res)
        # how much of the old figure is still showing? (her silhouette must cover it; the clean office shows through only in slivers)
        left = int(((old_mask > 0) & (cover < 0.5)).sum())
        print("old-figure pixels not covered by her:", left, "of", int((old_mask > 0).sum()))
        sys.exit(0)
    listen = video_frames(15.2, 17.0)
    check_no_hands(calm, matte, ref, "calm")
    check_no_hands(listen, matte, ref, "listen")
    print("no hand in any source frame")
    calm_c = compose(calm, plate, M, matte, body, old_mask, "calm")
    write_clip(calm_c, "lipsync", boomerang=False, crf=17)   # the GPU server turns it into a back-and-forth loop itself
    write_clip(calm_c, "idle", boomerang=True, crf=21)       # the same frames, forward then backward: what the page shows when nothing happens
    write_clip(compose(listen, plate, M, matte, body_mask(listen, matte), old_mask, "listen"), "listen", boomerang=True, crf=22)   # attentive: a smile and a slight head tilt, only while she listens
