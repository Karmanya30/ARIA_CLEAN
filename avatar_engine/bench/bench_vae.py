"""VAE decode variants for MuseTalk's 256px face (the dominant GPU cost)."""
import os, sys, time, json
ROOT = r"E:\MuseTalk\MuseTalk"; os.chdir(ROOT); sys.path.insert(0, ROOT)
import torch
torch.set_grad_enabled(False)
from diffusers import AutoencoderKL
dev = torch.device("cuda:0")
vae = AutoencoderKL.from_pretrained("models/sd-vae").to(dev).half().eval()
def sync(): torch.cuda.synchronize()
def run(name, fn, bs, shape=(4, 32, 32)):
    z = torch.randn(bs, *shape, device=dev, dtype=torch.float16)
    torch.cuda.reset_peak_memory_stats()
    ts = []
    for _ in range(5):
        sync(); t = time.perf_counter(); fn(z); sync(); ts.append(time.perf_counter() - t)
    dt = min(ts[1:])
    print(json.dumps({"variant": name, "bs": bs, "ms": round(dt * 1000, 1), "ms_per_frame": round(dt * 1000 / bs, 1),
                      "peak_mb": round(torch.cuda.max_memory_allocated() / 2**20)}), flush=True)
dec = lambda z: vae.decode(z).sample
for bs in (1, 2, 4, 8): run("sd-vae default", dec, bs)
vae.to(memory_format=torch.channels_last)
for bs in (4, 8, 12): run("sd-vae channels_last", lambda z: vae.decode(z.contiguous(memory_format=torch.channels_last)).sample, bs)
for bs in (8, 12): run("sd-vae channels_last, bottom 18/32 latent rows", lambda z: vae.decode(z[:, :, 14:].contiguous(memory_format=torch.channels_last)).sample, bs)
from diffusers import AutoencoderTiny
try:
    tiny = AutoencoderTiny.from_pretrained("madebyollin/taesd", torch_dtype=torch.float16).to(dev).eval()
    for bs in (8, 12, 16): run("taesd", lambda z: tiny.decode(z).sample, bs)
except Exception as e: print("taesd failed", e)
