"""MuseTalk 1.5 component benchmark on the local GPU (no mic, no network). Run with the MuseTalk env python:
   E:\MuseTalk\env\python.exe avatar_engine\bench\bench_musetalk.py"""
import os, sys, time, pickle, json
ROOT = os.environ.get("MUSETALK_DIR", r"E:\MuseTalk\MuseTalk")
os.chdir(ROOT); sys.path.insert(0, ROOT)
import numpy as np, torch, cv2
from transformers import WhisperModel
from musetalk.utils.audio_processor import AudioProcessor
from musetalk.utils.utils import load_all_model

torch.set_grad_enabled(False)
dev = torch.device("cuda:0")
torch.backends.cudnn.benchmark = os.environ.get("CB","0")=="1"
out = {}
t0 = time.time()
vae, unet, pe = load_all_model(unet_model_path="./models/musetalkV15/unet.pth", vae_type="sd-vae",
                               unet_config="./models/musetalkV15/musetalk.json", device=dev)
pe = pe.half().to(dev); vae.vae = vae.vae.half().to(dev); unet.model = unet.model.half().to(dev)
wh = WhisperModel.from_pretrained("./models/whisper").to(device=dev, dtype=torch.float16).eval()
ap = AudioProcessor(feature_extractor_path="./models/whisper")
torch.cuda.synchronize()
print("loaded", flush=True)
out["load_s"] = round(time.time() - t0, 1)
out["vram_after_load_mb"] = round(torch.cuda.memory_allocated() / 2**20)
ts = torch.tensor([0], device=dev)

def sync(): torch.cuda.synchronize()
# whisper features for N s of audio
import soundfile as sf
for secs in (1, 3, 8):
    sf.write("_b.wav", (np.random.randn(16000 * secs) * 0.05).astype(np.float32), 16000)
    for rep in range(3):
        sync(); t = time.perf_counter()
        feats, L = ap.get_audio_feature("_b.wav", weight_dtype=torch.float16)
        ch = ap.get_whisper_chunk(feats, dev, torch.float16, wh, L, fps=25, audio_padding_length_left=2, audio_padding_length_right=2)
        sync(); dt = time.perf_counter() - t
    out[f"whisper_{secs}s_ms"] = round(dt * 1000, 1)
os.remove("_b.wav")
# unet / vae per batch
lat = torch.randn(1, 8, 32, 32, device=dev, dtype=torch.float16)
for bs in (4, 8, 12, 16):
    x = lat.repeat(bs, 1, 1, 1); a = torch.randn(bs, 50, 384, device=dev, dtype=torch.float16)
    print("bs", bs, torch.cuda.memory_allocated()//2**20, flush=True)
    for rep in range(4):
        sync(); t = time.perf_counter()
        a2 = pe(a)
        sync(); t1 = time.perf_counter()
        pred = unet.model(x, ts, encoder_hidden_states=a2).sample
        sync(); t2 = time.perf_counter()
        img = vae.decode_latents(pred.to(vae.vae.dtype))
        sync(); t3 = time.perf_counter()
    out[f"bs{bs}"] = {"unet_ms": round((t2 - t1) * 1000, 1), "vae_ms": round((t3 - t2) * 1000, 1),
                      "gpu_fps": round(bs / (t3 - t), 1), "peak_vram_mb": round(torch.cuda.max_memory_allocated() / 2**20)}
print(json.dumps(out, indent=1), flush=True)
