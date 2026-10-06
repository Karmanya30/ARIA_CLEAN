r"""Draw thin silver wire-frame glasses as a transparent PNG overlay for the avatar photo (interface/avatar/glasses.png).

Placed from the face landmarks MuseTalk uses, so run it with MuseTalk's Python from the MuseTalk folder:

    cd E:\musetalk\MuseTalk
    E:\musetalk\env\python E:\ARIA\scripts\make_glasses.py E:\ARIA\interface\avatar\face.png E:\ARIA\interface\avatar\glasses.png

The overlay carries everything about the glasses (cast shadow, clear lenses with faint reflections, a shaded silver rim
with highlights, an arched bridge, hinge blocks, clear silicone nose pads on metal arms, thin temples that disappear
behind the hair), so the photo underneath stays untouched and the page can blink and lip-sync beneath it without ever
distorting the frames.
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
R = 0.42 * D                      # half the lens width
AX, AY = R, 0.90 * R              # slightly oval: a little wider than tall
T = 0.040 * R                     # thin wire rim
centers = [e + np.array([0, -0.03 * R]) for e in eyes]
S = 3  # draw at 3x and shrink: clean edges
big = lambda v: tuple(int(round(x)) for x in np.asarray(v, np.float32) * S)
blank = lambda: np.zeros((h * S, w * S), np.float32)
down = lambda m: cv2.resize(m, (w, h), interpolation=cv2.INTER_AREA)
blur = lambda m, sigma: cv2.GaussianBlur(m, (0, 0), sigma)

rim, lens, arms, bridge, hinge, padarm, pads = (blank() for _ in range(7))
for c in centers:
    cv2.ellipse(lens, big(c), (int(AX * S), int(AY * S)), 0, 0, 360, 1.0, -1, cv2.LINE_AA)
    cv2.ellipse(rim, big(c), (int((AX + T / 2) * S), int((AY + T / 2) * S)), 0, 0, 360, 1.0, int(T * S), cv2.LINE_AA)
# bridge: a slim arch at the upper third of the lenses
a, b = centers[0] + np.array([AX, -0.22 * AY]), centers[1] - np.array([AX, 0.22 * AY])
mid, half = (a + b) / 2, float(np.hypot(*(b - a))) / 2
cv2.ellipse(bridge, big(mid + np.array([0, 0.10 * R])), (int((half + T) * S), int(0.17 * R * S)), 0, 196, 344, 1.0, int(0.9 * T * S), cv2.LINE_AA)
fade = np.ones((h, w), np.float32)
xs = np.arange(w, dtype=np.float32)[None, :]
for c, ear, sgn in ((centers[0], kp[0], -1), (centers[1], kp[16], 1)):
    # hinge block on the outer upper corner, then a thin temple going back, fading out behind the hair
    hp = c + np.array([sgn * (AX + T * 0.5), -0.34 * AY])
    p0, p1 = hp + np.array([-sgn * 0.02 * R, -0.055 * R]), hp + np.array([sgn * 0.12 * R, 0.055 * R])
    cv2.rectangle(hinge, big(np.minimum(p0, p1)), big(np.maximum(p0, p1)), 1.0, -1, cv2.LINE_AA)
    start = hp + np.array([sgn * 0.11 * R, 0])
    end = np.array([ear[0] + sgn * 0.01 * D, start[1] + 0.05 * R])
    cv2.line(arms, big(start), big(end), 1.0, int(0.8 * T * S), cv2.LINE_AA)
    t = np.clip((xs - start[0]) / (end[0] - start[0]), 0, 1)
    fade = fade * np.where(np.sign(xs - c[0]) == sgn, 1 - np.clip((t - 0.10) / 0.70, 0, 1), 1)
# clear silicone nose pads on thin metal arms, on the inner lower side of each lens
for c, sgn in ((centers[0], 1), (centers[1], -1)):
    pc = c + np.array([sgn * 0.86 * AX, 0.30 * AY])
    cv2.line(padarm, big(c + np.array([sgn * 0.985 * AX, 0.12 * AY])), big(pc + np.array([sgn * 0.02 * R, -0.05 * R])), 1.0, int(0.75 * T * S), cv2.LINE_AA)
    cv2.ellipse(pads, big(pc), (int(0.055 * R * S), int(0.14 * R * S)), sgn * 14, 0, 360, 1.0, -1, cv2.LINE_AA)
rim, lens, arms, bridge, hinge, padarm, pads = map(down, (rim, lens, arms, bridge, hinge, padarm, pads))
wire = np.clip(rim + bridge + padarm, 0, 1)
frame = np.clip(wire + hinge + arms * fade, 0, 1)

yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
n0 = np.hypot((xx - centers[0][0]) / AX, (yy - centers[0][1]) / AY)
n1 = np.hypot((xx - centers[1][0]) / AX, (yy - centers[1][1]) / AY)
near = n1 < n0
cx = np.where(near, centers[1][0], centers[0][0]); cy = np.where(near, centers[1][1], centers[0][1]); rho = np.where(near, n1, n0)
theta = np.arctan2((yy - cy) / AY, (xx - cx) / AX)
facing = np.cos(theta - np.arctan2(-1.0, -1.0))              # 1 toward the light (upper left), -1 away
across = np.clip((rho - 1) * R / (T / 2), -1, 1)              # -1 inner edge .. +1 outer edge of the wire

layers = []  # (BGR colour or image, alpha), bottom to top
shadow = blur(np.roll(np.roll(frame, int(0.07 * R), 0), int(0.03 * R), 1), 0.05 * R)
layers.append((np.array([8, 8, 10], np.float32), 0.20 * np.clip(shadow, 0, 1)))                 # cast onto the face
layers.append((np.array([214, 206, 192], np.float32), 0.035 * lens))                            # very faint cool glass tint
for c in centers:
    sel = np.clip(lens * (np.hypot((xx - c[0]) / AX, (yy - c[1]) / AY) < 1), 0, 1)
    d = ((xx - c[0]) * 0.7071 + (yy - c[1]) * 0.7071) / R
    layers.append((np.array([255, 253, 250], np.float32), sel * (0.11 * np.exp(-((d + 0.45) / 0.12) ** 2) + 0.05 * np.exp(-((d - 0.32) / 0.05) ** 2))))  # window-light streaks
    ring = np.exp(-(((np.hypot((xx - c[0]) / AX, (yy - c[1]) / AY) - 0.965) / 0.022) ** 2))
    layers.append((np.array([255, 255, 255], np.float32), sel * ring * (0.06 + 0.16 * np.clip(facing, 0, 1) ** 2)))                  # inner bevel catching light
layers.append((np.array([222, 226, 230], np.float32), 0.34 * pads))                              # clear silicone pad body
tube = 1 - 0.30 * across ** 2
silver = np.array([214, 219, 224], np.float32)                                                    # bright polished silver, BGR
shade = (0.58 + 0.42 * (facing + 1) / 2) * tube
spec = np.clip(facing, 0, 1) ** 4 * np.clip(1 - np.abs(across) * 1.3, 0, 1)
colour = silver[None, None, :] * shade[..., None] + 160 * spec[..., None] * np.array([0.9, 0.95, 1.0], np.float32)
flat = silver[None, None, :] * 0.80 + 40 * np.clip(-(yy - cy) / R, 0, 1)[..., None]               # temples, hinge blocks: flatter metal
colour = np.where(((hinge + arms * fade) > wire)[..., None], flat, colour)
layers.append((colour, 0.96 * frame))

prem = np.zeros((h, w, 3), np.float32); alpha = np.zeros((h, w), np.float32)
for col, a_ in layers:
    a_ = np.clip(a_, 0, 1)
    col = np.broadcast_to(col, (h, w, 3))
    prem = col * a_[..., None] + prem * (1 - a_)[..., None]
    alpha = a_ + alpha * (1 - a_)
bgr = np.where(alpha[..., None] > 1e-4, prem / np.maximum(alpha[..., None], 1e-4), 0)
cv2.imwrite(dst, np.dstack([np.clip(bgr, 0, 255), np.clip(alpha * 255, 0, 255)]).astype(np.uint8))
print("written", dst, "lens half-width", round(R), "px")
