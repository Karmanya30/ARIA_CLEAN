r"""
MuseTalk v1.5 lip-sync server for ARIA's Live Avatar. Run it with the Python environment that has MuseTalk installed:

    set MUSETALK_DIR=E:\musetalk\MuseTalk
    E:\musetalk\env\python scripts\musetalk_server.py --source interface\avatar\face.png --port 8010

Models stay loaded on the GPU and the avatar (face box, latents, blend masks) is prepared once and cached, so a
request only runs Whisper features + UNet + VAE decode, exactly MuseTalk's own realtime path. Requests are served in
arrival order, and a client that leaves mid-stream releases the GPU at once.

POST /lipsync   body: a WAV clip  ->  stream: u32 frame count, then per frame u32 length + JPEG (header X-Fps)
GET  /idle.jpg  the resting frame
GET  /health    {"ready": bool, "fps": N, "size": [w, h]}
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import os
import pickle
import queue
import struct
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import cv2
import numpy as np
import torch
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from transformers import WhisperModel

ROOT = os.environ.get("MUSETALK_DIR") or os.path.dirname(os.path.abspath(__file__))  # a MuseTalk checkout with models/
LAUNCH_DIR = os.getcwd()  # --source is relative to where this was started, not to the MuseTalk folder
os.chdir(ROOT)
sys.path.insert(0, ROOT)
from musetalk.utils.audio_processor import AudioProcessor  # noqa: E402
from musetalk.utils.blending import get_image_blending, get_image_prepare_material  # noqa: E402
from musetalk.utils.face_parsing import FaceParsing  # noqa: E402
from musetalk.utils.utils import datagen, load_all_model  # noqa: E402

FPS, EXTRA_MARGIN, MIN_SIDE, MAX_OUT = 25, 10, 640, 720
torch.backends.cudnn.benchmark = True  # fixed-size batches: let cuDNN pick the fastest kernels once
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Fps"])
S: dict = {"ready": False}
gpu = threading.Lock()
_turns, _tickets, _serving = threading.Condition(), itertools.count(), 0  # requests use the GPU strictly in arrival order


def _load_models(batch: int) -> None:
    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    vae, unet, pe = load_all_model(unet_model_path="./models/musetalkV15/unet.pth", vae_type="sd-vae",
                                   unet_config="./models/musetalkV15/musetalk.json", device=device)
    pe = pe.half().to(device)
    vae.vae = vae.vae.half().to(device)
    unet.model = unet.model.half().to(device)
    whisper = WhisperModel.from_pretrained("./models/whisper").to(device=device, dtype=unet.model.dtype).eval()
    whisper.requires_grad_(False)
    S.update(device=device, vae=vae, unet=unet, pe=pe, whisper=whisper, batch=batch,
             audio=AudioProcessor(feature_extractor_path="./models/whisper"), dtype=unet.model.dtype,
             timesteps=torch.tensor([0], device=device), fp=FaceParsing(left_cheek_width=90, right_cheek_width=90))


def _frames_from(source: str) -> list[np.ndarray]:
    """A photo becomes one frame (upscaled: MuseTalk works on a 256 px face crop); a video gives all its frames."""
    if os.path.splitext(source)[1].lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
        img = cv2.imread(source, cv2.IMREAD_COLOR)
        k = MIN_SIDE / min(img.shape[:2])
        if k > 1:  # tiny photo: enlarge so the face crop has detail
            img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_LANCZOS4)
        k = MAX_OUT / max(img.shape[:2])
        if k < 1:  # large photo: every frame is blended on the CPU at this size, so keep it no bigger than it is shown
            img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
        return [img]
    cap, out = cv2.VideoCapture(source), []
    while True:
        ok, frame = cap.read()
        if not ok:
            return out
        out.append(frame)


def _prepare(source: str) -> None:
    """MuseTalk's Avatar.prepare_material, minus its interactive prompts; cached per source file content."""
    key = hashlib.sha1(open(source, "rb").read()).hexdigest()[:12]
    cache = f"./results/v15/avatars/aria_{key}.pkl"
    if os.path.exists(cache):
        with open(cache, "rb") as f:
            A = pickle.load(f)
        A["latents"] = [t.to(S["device"]) for t in A["latents"]]
    else:
        from musetalk.utils.preprocessing import get_landmark_and_bbox  # mmpose: only needed to prepare

        frames = _frames_from(source)
        tmp = tempfile.mkdtemp()
        paths = []
        for i, fr in enumerate(frames):
            paths.append(os.path.join(tmp, f"{i:08d}.png"))
            cv2.imwrite(paths[-1], fr)
        coords, frames = get_landmark_and_bbox(paths, 0)
        keep_c, keep_f, latents = [], [], []
        for (x1, y1, x2, y2), fr in zip(coords, frames):
            if (x1, y1, x2, y2) == (0.0, 0.0, 0.0, 0.0):
                continue  # no face in this frame
            y2 = min(y2 + EXTRA_MARGIN, fr.shape[0])
            crop = cv2.resize(fr[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
            latents.append(S["vae"].get_latents_for_unet(crop))
            keep_c.append([x1, y1, x2, y2])
            keep_f.append(fr)
        if not keep_f:
            raise RuntimeError(f"MuseTalk found no face in {source}")
        frames, coords = keep_f + keep_f[::-1], keep_c + keep_c[::-1]
        masks, boxes = [], []
        for fr, box in zip(frames, coords):
            mask, crop_box = get_image_prepare_material(fr, box, fp=S["fp"], mode="jaw")
            masks.append(mask)
            boxes.append(crop_box)
        A = {"frames": frames, "coords": coords, "latents": latents + latents[::-1], "masks": masks, "mask_boxes": boxes}
        os.makedirs(os.path.dirname(cache), exist_ok=True)
        with open(cache, "wb") as f:
            pickle.dump({**A, "latents": [t.cpu() for t in A["latents"]]}, f)
    h, w = A["frames"][0].shape[:2]
    A["scale"] = min(1.0, MAX_OUT / max(h, w))
    S["avatar"] = A


def _jpeg(frame: np.ndarray) -> bytes:
    s = S["avatar"]["scale"]
    if s < 1:
        frame = cv2.resize(frame, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    return cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()


def _blend(k: int, face: np.ndarray) -> bytes:
    A = S["avatar"]
    x1, y1, x2, y2 = A["coords"][k]
    face = cv2.resize(face.astype(np.uint8), (x2 - x1, y2 - y1))
    out = get_image_blending(copy.deepcopy(A["frames"][k]), face, [x1, y1, x2, y2], A["masks"][k], A["mask_boxes"][k])
    return _jpeg(out)


def _gpu_worker(wav: bytes, q: queue.Queue, ticket: int, stop: threading.Event) -> None:
    """UNet + VAE on the GPU, one batch at a time, handing each batch's faces to the CPU side as soon as it is ready.
    Waits for its turn (arrival order); gives up as soon as the client has gone, so an abandoned request cannot hold the GPU."""
    global _serving
    A = S["avatar"]

    def put(item) -> bool:
        deadline = time.time() + 30
        while not stop.is_set() and time.time() < deadline:
            try:
                q.put(item, timeout=0.2)
                return True
            except queue.Full:
                pass
        return False

    with _turns:
        _turns.wait_for(lambda: _serving == ticket)
    try:
        if stop.is_set():  # left while waiting for its turn
            return
        with gpu, torch.no_grad():
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                f.write(wav)
            try:
                feats, length = S["audio"].get_audio_feature(f.name, weight_dtype=S["dtype"])
                chunks = S["audio"].get_whisper_chunk(feats, S["device"], S["dtype"], S["whisper"], length, fps=FPS,
                                                      audio_padding_length_left=2, audio_padding_length_right=2)
            finally:
                os.unlink(f.name)
            if not put(("n", len(chunks))):
                return
            for whisper_batch, latent_batch in datagen(chunks, A["latents"], S["batch"], device=S["device"]):
                real = len(whisper_batch)
                if real < S["batch"]:  # a new batch size makes cuDNN re-tune for seconds: always run the full size, drop the padding
                    pad = S["batch"] - real
                    whisper_batch = torch.cat([whisper_batch, whisper_batch[-1:].expand(pad, *whisper_batch.shape[1:])])
                    latent_batch = torch.cat([latent_batch, latent_batch[-1:].expand(pad, *latent_batch.shape[1:])])
                audio_batch = S["pe"](whisper_batch.to(S["device"]))
                pred = S["unet"].model(latent_batch.to(S["device"], dtype=S["unet"].model.dtype), S["timesteps"],
                                       encoder_hidden_states=audio_batch).sample
                if not put(("faces", S["vae"].decode_latents(pred.to(dtype=S["vae"].vae.dtype))[:real])):
                    return
    except Exception as exc:  # surfaced to the consumer instead of dying silently in the thread
        put(("error", exc))
    finally:
        put(("end", None))
        with _turns:
            _serving += 1
            _turns.notify_all()


def _generate(wav: bytes, ticket: int):
    """Stream frames. The GPU keeps working on the next batch while the CPU blends and encodes the previous one."""
    q: queue.Queue = queue.Queue(maxsize=3)
    stop = threading.Event()
    threading.Thread(target=_gpu_worker, args=(wav, q, ticket, stop), daemon=True).start()
    n_frames = len(S["avatar"]["frames"])
    try:
        yield from _consume(q, n_frames)
    finally:
        stop.set()  # the client left (Stop pressed, tab closed) or we finished: release the GPU turn either way


def _consume(q: queue.Queue, n_frames: int):
    i, t0 = 0, time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as pool:
        while True:
            kind, payload = q.get()
            if kind == "end":
                break
            if kind == "error":
                raise payload
            if kind == "n":
                yield struct.pack("<I", payload)
                continue
            jpgs = list(pool.map(_blend, [(i + d) % n_frames for d in range(len(payload))], payload))
            for jpg in jpgs:
                yield struct.pack("<I", len(jpg)) + jpg
            i += len(payload)
    total = time.perf_counter() - t0
    print(f"{i} frames in {total:.2f}s ({i / max(total, 1e-6):.1f} fps)", flush=True)


@app.post("/lipsync")
async def lipsync(request: Request):
    wav = await request.body()
    return StreamingResponse(_generate(wav, next(_tickets)), media_type="application/octet-stream", headers={"X-Fps": str(FPS)})


@app.get("/idle.jpg")
def idle():
    return Response(_jpeg(S["avatar"]["frames"][0]), media_type="image/jpeg", headers={"Cache-Control": "no-cache"})


@app.get("/health")
def health():
    A = S.get("avatar")
    size = None
    if A:
        h, w = A["frames"][0].shape[:2]
        size = [round(w * A["scale"]), round(h * A["scale"])]
    return {"ready": S["ready"], "fps": FPS, "size": size}


if __name__ == "__main__":
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="photo or short video of the face")
    ap.add_argument("--port", type=int, default=8010)
    ap.add_argument("--fps", type=int, default=15, help="mouth frames per second of speech: 15 keeps an RTX 4060 laptop just ahead of real time (about 1.05x); 25 needs a faster GPU")
    ap.add_argument("--batch", type=int, default=12, help="frames per GPU batch; small = first frames sooner, large = higher throughput")
    a = ap.parse_args()
    FPS = a.fps
    t = time.time()
    _load_models(a.batch)
    _prepare(os.path.abspath(os.path.join(LAUNCH_DIR, a.source)))
    S["ready"] = True
    # warm the GPU kernels so the first real request is not the slow one
    silence = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
    import soundfile as sf

    sf.write(silence, np.zeros(16000, dtype=np.float32), 16000)
    for _ in _generate(open(silence, "rb").read(), next(_tickets)):
        pass
    os.unlink(silence)
    print(f"MuseTalk ready in {time.time() - t:.0f}s on {S['device']}", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=a.port)
