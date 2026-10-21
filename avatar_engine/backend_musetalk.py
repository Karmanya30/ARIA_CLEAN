"""MuseTalk 1.5 backend (fp16, in-process). Uses the MuseTalk checkout/env (see config.MUSETALK_DIR) for the models.

Speed work on top of stock MuseTalk (measured on an RTX 4060 Laptop, see BENCHMARKS.md):
  * 'half' VAE mode decodes only the lower 20/32 latent rows (the model only changes the mouth/jaw half), ~1.8x faster
    than the full VAE decode, which is the dominant GPU cost;
  * no autograd, fixed small batches, OOM retry with split batches.
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path

import cv2
import numpy as np
from loguru import logger

from . import config
from .backend_base import Backend, GpuOom
from .compositor import ReplicaData

MARGIN = 10          # extra px below the chin box, as in MuseTalk's own preparation
LAT_FROM = 12        # 'half' mode: decode latent rows 12..31; the first 4 rows are decoder context and are dropped
CTX_PX = (LAT_FROM + 4) * 8   # face row where the decoded lower half is spliced onto the original crop (= 128)


def _is_oom(e: BaseException) -> bool:
    s = str(e).lower()
    return "out of memory" in s or "alloc_failed" in s or "cublas_status_alloc" in s


class MuseTalkBackend(Backend):
    name = "musetalk-1.5"

    def __init__(self, vae_mode: str | None = None, batch: int | None = None):
        self.vae_mode = vae_mode or config.VAE_MODE
        self.batch = batch or config.BATCH
        self.S: dict = {}
        self.gpu = threading.Lock()

    # ------------------------------------------------------------------ models
    def load(self) -> None:
        root = str(config.MUSETALK_DIR)
        for s in (sys.stdout, sys.stderr):
            getattr(s, "reconfigure", lambda **k: None)(encoding="utf-8", errors="replace")
        os.chdir(root)   # MuseTalk uses paths relative to its checkout
        for p in (root, str(config.ROOT)):
            if p not in sys.path:
                sys.path.insert(0, p)
        import torch
        from transformers import WhisperModel

        from musetalk.utils.audio_processor import AudioProcessor
        from musetalk.utils.face_parsing import FaceParsing
        from musetalk.utils.utils import load_all_model

        torch.set_grad_enabled(False)
        torch.backends.cudnn.benchmark = os.environ.get("AVATAR_CUDNN_BENCH", "0") == "1"
        dev = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        vae, unet, pe = load_all_model(unet_model_path="./models/musetalkV15/unet.pth", vae_type="sd-vae",
                                       unet_config="./models/musetalkV15/musetalk.json", device=dev)
        pe = pe.half().to(dev)
        vae.vae = vae.vae.half().to(dev)
        unet.model = unet.model.half().to(dev)
        whisper = WhisperModel.from_pretrained("./models/whisper").to(device=dev, dtype=torch.float16).eval()
        whisper.requires_grad_(False)
        if dev.type == "cuda":   # cap the allocator: cuDNN's workspace tries otherwise balloon the cache to the whole card
            torch.cuda.set_per_process_memory_fraction(float(os.environ.get("AVATAR_VRAM_FRACTION", "0.6")))
        self.S.update(torch=torch, dev=dev, vae=vae, unet=unet, pe=pe, whisper=whisper,
                      audio=AudioProcessor(feature_extractor_path="./models/whisper"),
                      ts=torch.tensor([0], device=dev), fp=FaceParsing(left_cheek_width=90, right_cheek_width=90))
        if self.vae_mode == "taesd":
            self._load_taesd()
        self._warm()

    def _load_taesd(self) -> None:
        from diffusers import AutoencoderTiny
        t = self.S["torch"]
        self.S["tiny"] = AutoencoderTiny.from_pretrained("madebyollin/taesd", torch_dtype=t.float16).to(self.S["dev"]).eval()

    def _warm(self) -> None:
        """Run the whole generation path once so kernels/allocations are ready before the first real request."""
        np_ = np.zeros(16000, np.float32)
        t = self.S["torch"]
        lat = t.zeros(self.batch, 8, 32, 32, device=self.S["dev"], dtype=t.float16)
        for _ in range(2):
            self._gen_batch(self._whisper(np_, 25)[:self.batch], lat, None)

    # ------------------------------------------------------------------ generation
    def _whisper(self, wav16: np.ndarray, fps: int):
        S, t = self.S, self.S["torch"]
        seg = 30 * 16000
        feats = [S["audio"].feature_extractor(wav16[i:i + seg], return_tensors="pt", sampling_rate=16000).input_features.to(t.float16)
                 for i in range(0, max(len(wav16), 1), seg)]
        return S["audio"].get_whisper_chunk(feats, S["dev"], t.float16, S["whisper"], len(wav16), fps=fps,
                                            audio_padding_length_left=2, audio_padding_length_right=2)

    def _gen_batch(self, wchunks, latents, crops) -> np.ndarray:
        """One UNet + VAE pass -> (n,256,256,3) BGR uint8."""
        S, t = self.S, self.S["torch"]
        pred = S["unet"].model(latents, S["ts"], encoder_hidden_states=S["pe"](wchunks.to(S["dev"]))).sample
        mode = self.vae_mode
        if mode == "taesd":
            img = S["tiny"].decode(pred).sample
        else:
            z = (pred / S["vae"].scaling_factor).contiguous()
            if mode == "half":
                img = S["vae"].vae.decode(z[:, :, LAT_FROM:].contiguous()).sample[:, :, CTX_PX - LAT_FROM * 8:]   # rows 128..255
            else:
                img = S["vae"].vae.decode(z).sample
        img = ((img.float() / 2 + 0.5).clamp(0, 1) * 255).round().to(t.uint8).permute(0, 2, 3, 1).flip(-1).cpu().numpy()
        if mode == "half":
            top = np.stack(crops)[:, :CTX_PX] if crops is not None else np.zeros((len(img), CTX_PX, 256, 3), np.uint8)
            img = np.concatenate([top, img], axis=1)
        return np.ascontiguousarray(img)

    def lipsync(self, rep: ReplicaData, wav16: np.ndarray, fps: int, start_idx: int, cancel: threading.Event):
        S, t = self.S, self.S["torch"]
        n_lat = len(rep.extra["latents"])
        n = int(len(wav16) / 16000 * fps)
        if n <= 0:
            return
        lats = rep.extra.get("latents_gpu")
        if lats is None:
            lats = rep.extra["latents_gpu"] = t.cat([x.to(S["dev"], t.float16) for x in rep.extra["latents"]], 0)
        from .compositor import pingpong
        with self.gpu:
            wc = self._whisper(wav16, fps)[:n]
            b0 = 0
            while b0 < n:
                if cancel.is_set():
                    return
                bs = min(self.batch, n - b0)
                idx = [pingpong(start_idx + int(round((b0 + i) * 25 / fps)), n_lat) for i in range(bs)]
                try:
                    out = self._gen_batch(wc[b0:b0 + bs], lats[idx], [rep.crops[i] for i in idx] if self.vae_mode == "half" else None)
                except (RuntimeError, MemoryError) as e:
                    if not _is_oom(e):
                        raise
                    t.cuda.empty_cache()
                    logger.warning(f"GPU out of memory at batch {self.batch}: {e}")
                    if self.batch > 2:
                        self.batch = max(2, self.batch // 2)   # retry the same frames with smaller batches
                        continue
                    raise GpuOom(str(e)) from e
                b0 += bs
                yield out

    def downgrade(self) -> str | None:
        if self.vae_mode != "taesd":
            try:
                self._load_taesd()
            except Exception:
                return None
            self.vae_mode = "taesd"
            self.S["torch"].cuda.empty_cache()
            return "decoder switched to TAESD (faster, softer)"
        return None

    def info(self) -> dict:
        t = self.S.get("torch")
        if t is None or not t.cuda.is_available():
            return {"gpu": None, "vram_used_mb": 0}
        free, total = t.cuda.mem_get_info()
        return {"gpu": t.cuda.get_device_name(0), "vram_used_mb": round((total - free) / 2**20), "vram_total_mb": round(total / 2**20),
                "process_vram_mb": round(t.cuda.memory_reserved() / 2**20)}

    # ------------------------------------------------------------------ replicas
    def _frames_from(self, src: Path) -> list[np.ndarray]:
        if src.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".bmp"):
            img = cv2.imread(str(src), cv2.IMREAD_COLOR)
            if img is None:
                raise RuntimeError("cannot read the image")
            k = 640 / min(img.shape[:2])
            if k > 1:
                img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_LANCZOS4)
            k = 1440 / max(img.shape[:2])
            if k < 1:
                img = cv2.resize(img, None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
            return [img]
        cap = cv2.VideoCapture(str(src))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25
        step = max(1, round(fps / 25))
        out, i = [], 0
        while len(out) < config.MAX_VIDEO_FRAMES:
            ok, fr = cap.read()
            if not ok:
                break
            if i % step == 0:
                k = 720 / max(fr.shape[:2])
                out.append(cv2.resize(fr, None, fx=k, fy=k, interpolation=cv2.INTER_AREA) if k < 1 else fr)
            i += 1
        cap.release()
        if not out:
            raise RuntimeError("cannot read the video")
        return out

    def _matte(self, img: np.ndarray) -> np.ndarray | None:
        path = config.MODEL_DIR / "u2net_human_seg.onnx"
        if not path.exists():
            return None
        try:
            import onnxruntime as ort
            sess = self.S.get("u2net") or ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
            self.S["u2net"] = sess
            x = cv2.resize(img, (320, 320), interpolation=cv2.INTER_AREA)[..., ::-1].astype(np.float32) / 255.0
            x = ((x - (0.485, 0.456, 0.406)) / (0.229, 0.224, 0.225)).transpose(2, 0, 1)[None].astype(np.float32)
            m = sess.run(None, {sess.get_inputs()[0].name: x})[0][0, 0]
            m = (m - m.min()) / max(m.max() - m.min(), 1e-6)
            m = cv2.resize(m, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_CUBIC)
            m = cv2.GaussianBlur(np.clip((m - 0.1) / 0.8, 0, 1).astype(np.float32), (0, 0), 1.5)
            return m
        except Exception:
            return None

    def prepare(self, src: Path, dest: Path) -> dict:
        S, t = self.S, self.S["torch"]
        with self.gpu:
            from musetalk.utils import preprocessing as pp
            from musetalk.utils.blending import get_crop_box, get_image_prepare_material

            frames = self._frames_from(src)
            tmp = tempfile.mkdtemp()
            paths = []
            for i, fr in enumerate(frames):
                paths.append(os.path.join(tmp, f"{i:08d}.png"))
                cv2.imwrite(paths[-1], fr)
            coords, frames = pp.get_landmark_and_bbox(paths, 0)
            for p in paths:
                os.unlink(p)
            os.rmdir(tmp)
            keep = [(c, f) for c, f in zip(coords, frames) if tuple(c) != (0.0, 0.0, 0.0, 0.0)]
            if not keep:
                raise RuntimeError("no face found: use a clear, front-facing photo or video")
            if len(keep) < len(frames) * 0.8 and len(frames) > 1:
                raise RuntimeError("the face is not visible in most of the video")
            lm = None
            if len(keep) == 1:
                from mmpose.apis import inference_topdown
                from mmpose.structures import merge_data_samples
                kp = merge_data_samples(inference_topdown(pp.model, keep[0][1])).pred_instances.keypoints[0][23:91]
                lm = kp.astype(np.float32)
            # pad the frames so MuseTalk's 1.5x paste region always fits inside them
            pad = [0, 0, 0, 0]
            for c, f in keep:
                (x1, y1, x2, y2), h, w = [int(v) for v in c], *f.shape[:2]
                cb, _ = get_crop_box((x1, y1, x2, y2), 1.5)
                pad = [max(pad[0], -cb[0]), max(pad[1], -cb[1]), max(pad[2], cb[2] - w), max(pad[3], cb[3] - h)]
            l, tp, r, b = pad
            fr_list, c_list, crops, latents = [], [], [], []
            for c, f in keep:
                x1, y1, x2, y2 = [int(v) for v in c]
                if any(pad):
                    f = cv2.copyMakeBorder(f, tp, b, l, r, cv2.BORDER_REPLICATE)
                x1, x2, y1, y2 = x1 + l, x2 + l, y1 + tp, y2 + tp
                y2 = min(y2 + MARGIN, f.shape[0])
                crop = cv2.resize(f[y1:y2, x1:x2], (256, 256), interpolation=cv2.INTER_LANCZOS4)
                latents.append(S["vae"].get_latents_for_unet(crop).cpu())
                fr_list.append(f)
                c_list.append((x1, y1, x2, y2))
                crops.append(crop)
            if len(fr_list) > 1:   # loop forwards then backwards, like MuseTalk's own realtime avatars
                fr_list, c_list, crops, latents = fr_list + fr_list[::-1][1:-1], c_list + c_list[::-1][1:-1], crops + crops[::-1][1:-1], latents + latents[::-1][1:-1]
            masks, boxes = [], []
            for f, bx in zip(fr_list, c_list):
                m, cb = get_image_prepare_material(f, bx, fp=S["fp"], mode="jaw")
                masks.append(np.asarray(m, np.float32) / 255.0)
                boxes.append(tuple(int(v) for v in cb))
            H, W = fr_list[0].shape[:2]
            for xs, ys, xe, ye in boxes:
                assert 0 <= xs < xe <= W and 0 <= ys < ye <= H, "face too close to the photo edge"
            rep = ReplicaData(id="", kind="photo" if len(fr_list) == 1 else "video", frames=fr_list, coords=c_list, mask_boxes=boxes,
                              alphas=masks, crops=crops, lm=(lm + [l, tp]) if lm is not None and len(fr_list) == 1 else None,
                              matte=self._matte(fr_list[0]) if len(fr_list) == 1 else None, extra={"latents": latents})
            self.save(dest, rep)
        x1, y1, x2, y2 = c_list[0]
        return {"face_box": [x1, y1, x2, y2], "size": [W, H], "frames": len(fr_list), "matte": rep.matte is not None}
