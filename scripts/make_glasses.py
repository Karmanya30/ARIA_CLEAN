r"""Draw round glasses as a transparent PNG overlay for the avatar photo (interface/avatar/glasses.png).

Placed from the face landmarks MuseTalk uses, so run it with MuseTalk's Python from the MuseTalk folder:

    cd E:\musetalk\MuseTalk
    E:\musetalk\env\python E:\ARIA\scripts\make_glasses.py E:\ARIA\interface\avatar\face.png E:\ARIA\interface\avatar\glasses.png

The overlay carries everything about the glasses (cast shadow, lens tint and reflections, a shaded metal rim with a
highlight, nose pads, temple arms that disappear behind the hair), so the photo underneath stays untouched and the page
can blink and lip-sync beneath it without ever distorting the frames.
"""
import sys

import cv2
import numpy as np

src, dst = sys.argv[1], sys.argv[2]
from mmpose.apis import inference_topdown, init_model  # noqa: E402

img = cv2.imread(src, cv2.IMREAD_COLOR)
h, w = img.shape[:2]
model = init_model("./musetalk/utils/dwpose/rtmpose-l_8xb32-270e_coco-ubody-wholebody-384x288.py", "./models/dwpose/dw-ll_ucoco_384.pth", device="cuda:0")
kp = inference_topdown(model, img)[0].pred_instances.keypoints[0][23:91]  # the 68 face landmarks
eyes = [kp[36:42].mean(0), kp[42:48].mean(0)]  # image-left eye first
D = float(np.hypot(*(eyes[1] - eyes[0])))
R, T = 0.40 * D, 0.072 * 0.40 * D  # lens radius, rim thickness
centers = [e + np.array([0, -0.04 * R]) for e in eyes]
S = 3  # draw at 3x and shrink: clean edges
big = lambda v: tuple(int(x) for x in np.asarray(v, np.float32) * S)
blank = lambda: np.zeros((h * S, w * S), np.float32)
down = lambda m: cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)
blur = lambda m, sigma: cv2.GaussianBlur(m, (0, 0), sigma)

rim, lens, arms, bridge, pads = blank(), blank(), blank(), blank(), blank()
for c in centers:
    cv2.circle(lens, big(c), int(R * S), 1.0, -1, cv2.LINE_AA)
    cv2.circle(rim, big(c), int((R + T / 2) * S), 1.0, int(T * S), cv2.LINE_AA)
a, b = centers[0] + np.array([R + T / 2, 0]), centers[1] - np.array([R + T / 2, 0])
mid, half = (a + b) / 2, float(np.hypot(*(b - a))) / 2
cv2.ellipse(bridge, big(mid + np.array([0, 0.30 * R])), (int((half + T * 0.4) * S), int(0.34 * R * S)), 0, 208, 332, 1.0, int(0.85 * T * S), cv2.LINE_AA)
# temple arms: from the hinge on the outer edge of each lens back past the face edge, fading out as they go behind the hair
fade = np.ones((h, w), np.float32)
for c, ear, sgn in ((centers[0], kp[0], -1), (centers[1], kp[16], 1)):
    start = c + np.array([sgn * (R + T / 2), -0.08 * R])
    end = np.array([ear[0] + sgn * 0.16 * D, start[1] + 0.05 * R])
    cv2.line(arms, big(start), big(end), 1.0, int(0.85 * T * S), cv2.LINE_AA)
    xs = np.arange(w, dtype=np.float32)[None, :]
    t = np.clip((xs - start[0]) / (end[0] - start[0]), 0, 1)  # 0 at the hinge, 1 at the far end
    fade = fade * np.where(np.sign(xs - c[0]) == sgn, 1 - np.clip((t - 0.40) / 0.60, 0, 1), 1)
# nose pads: small translucent ovals where the frame rests on the nose
for c, sgn in ((centers[0], 1), (centers[1], -1)):
    cv2.ellipse(pads, big(c + np.array([sgn * 0.80 * R, 0.30 * R])), (int(0.06 * R * S), int(0.15 * R * S)), sgn * 12, 0, 360, 1.0, -1, cv2.LINE_AA)
rim, lens, arms, bridge, pads = map(down, (rim, lens, arms, bridge, pads))
metal = np.clip(rim + bridge, 0, 1)
frame = np.clip(metal + arms * fade, 0, 1)

yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
# per-pixel direction/distance to the nearest lens centre, for shading the rim like a tube lit from the upper left
d0 = np.hypot(xx - centers[0][0], yy - centers[0][1]); d1 = np.hypot(xx - centers[1][0], yy - centers[1][1])
near = (d1 < d0)
cx = np.where(near, centers[1][0], centers[0][0]); cy = np.where(near, centers[1][1], centers[0][1]); dist = np.where(near, d1, d0)
theta = np.arctan2(yy - cy, xx - cx)
facing = np.cos(theta - np.arctan2(-1.0, -1.0))           # 1 toward the light (upper left), -1 away
across = np.clip((dist - (R + T / 2)) / (T / 2), -1, 1)    # -1 inner edge .. +1 outer edge of the rim

layers = []  # (BGR colour image or triple, alpha)
shadow = blur(np.roll(np.roll(frame, int(0.10 * R), 0), int(0.05 * R), 1), 0.075 * R)
layers.append((np.array([8, 8, 10], np.float32), 0.34 * np.clip(shadow, 0, 1) * (1 - lens * 0.0)))              # cast onto the face
inner = blur(np.roll(rim, int(0.06 * R), 0), 0.05 * R) * lens
layers.append((np.array([10, 10, 14], np.float32), 0.20 * np.clip(inner, 0, 1)))                                # rim shadow on the lens/eyelid
layers.append((np.array([214, 205, 188], np.float32), 0.055 * lens))                                            # faint cool glass tint
band = lambda cxy, off, width: np.exp(-((((xx - cxy[0]) * 0.7071 + (yy - cxy[1]) * 0.7071) / R - off) / width) ** 2)
for c in centers:
    sel = np.clip(lens * (np.hypot(xx - c[0], yy - c[1]) < R), 0, 1)
    layers.append((np.array([255, 252, 248], np.float32), sel * (0.17 * band(c, -0.45, 0.10) + 0.09 * band(c, 0.30, 0.05))))  # window-light streaks
    ring = np.exp(-(((np.hypot(xx - c[0], yy - c[1]) - (R - 0.045 * R)) / (0.018 * R)) ** 2))
    layers.append((np.array([255, 255, 255], np.float32), sel * ring * (0.10 + 0.22 * np.clip(facing, 0, 1) ** 2)))               # bevel catching light
tube = 1 - 0.42 * across ** 2                                     # rounder shading across the rim width
body = np.array([34, 36, 44], np.float32)                          # dark gunmetal, BGR
shade = (0.62 + 0.38 * (facing + 1) / 2) * tube
colour = body[None, None, :] * shade[..., None] + 205 * (np.clip(facing, 0, 1) ** 6 * np.clip(1 - np.abs(across) * 1.4, 0, 1))[..., None] * np.array([0.82, 0.92, 1.0], np.float32)
arm_c = body[None, None, :] * 0.9 + 22 * np.clip(-(yy - cy) / R, 0, 1)[..., None]  # arms: flat dark, slightly lighter on top
colour = np.where((arms * fade > metal)[..., None], arm_c, colour)
layers.append((colour, 0.96 * frame))
layers.append((np.array([200, 205, 215], np.float32), 0.30 * pads))
layers.append((np.array([20, 20, 24], np.float32), 0.16 * blur(pads, 0.02 * R)))

prem = np.zeros((h, w, 3), np.float32); alpha = np.zeros((h, w), np.float32)
for col, a in layers:
    a = np.clip(a, 0, 1)
    col = np.broadcast_to(col, (h, w, 3))
    prem = col * a[..., None] + prem * (1 - a)[..., None]
    alpha = a + alpha * (1 - a)
bgr = np.where(alpha[..., None] > 1e-4, prem / np.maximum(alpha[..., None], 1e-4), 0)
cv2.imwrite(dst, np.dstack([np.clip(bgr, 0, 255), np.clip(alpha * 255, 0, 255)]).astype(np.uint8))
print("written", dst, "lens radius", round(R), "px")
