"""
ARIA's lip-sync GPU service on Modal: the "New ARIA Avatar" (scripts/musetalk_server.py) running on a GPU that exists only
while someone is using it. It starts on the first request, stops after IDLE_SECONDS without one, and bills per second.

    python -m modal secret create aria-lipsync ARIA_LIPSYNC_SECRET=<the same value as ARIA_LIPSYNC_SECRET in the server's .env>
    python -m modal deploy deploy/modal_lipsync.py        # first build takes a while (PyTorch, mmcv, the models); later ones are cached

Settings (environment, read when you deploy): ARIA_LIPSYNC_GPU (default L4), ARIA_LIPSYNC_MAX_CONTAINERS (default 2, the cap on
simultaneous GPUs and so on the bill), ARIA_LIPSYNC_IDLE_SECONDS (default 120).
"""
import os
import subprocess
from pathlib import Path

import modal

ROOT = Path(__file__).resolve().parent.parent
MUSE, ARIA, MODELS = "/opt/MuseTalk", "/opt/aria", "/opt/MuseTalk/models"
GPUS = [g.strip() for g in os.environ.get("ARIA_LIPSYNC_GPU", "L4,A10,T4").split(",")]  # in order of preference: Modal takes the first one that has capacity
GPU = GPUS if len(GPUS) > 1 else GPUS[0]
MAX_CONTAINERS = int(os.environ.get("ARIA_LIPSYNC_MAX_CONTAINERS", "2"))
IDLE_SECONDS = int(os.environ.get("ARIA_LIPSYNC_IDLE_SECONDS", "120"))

app = modal.App("aria-lipsync")
cache = modal.Volume.from_name("aria-lipsync-cache", create_if_missing=True)  # the prepared avatars survive a cold start


def download_weights() -> None:
    """MuseTalk's download_weights.sh, minus the syncnet (training only) and the China mirror."""
    import urllib.request

    import gdown
    from huggingface_hub import hf_hub_download

    for repo, files, sub in [
        ("TMElyralab/MuseTalk", ["musetalkV15/musetalk.json", "musetalkV15/unet.pth"], ""),
        ("stabilityai/sd-vae-ft-mse", ["config.json", "diffusion_pytorch_model.bin"], "sd-vae"),
        ("openai/whisper-tiny", ["config.json", "pytorch_model.bin", "preprocessor_config.json"], "whisper"),
        ("yzd-v/DWPose", ["dw-ll_ucoco_384.pth"], "dwpose"),
    ]:
        for name in files:
            hf_hub_download(repo, name, local_dir=os.path.join(MODELS, sub) if sub else MODELS)
    parse = os.path.join(MODELS, "face-parse-bisent")
    os.makedirs(parse, exist_ok=True)
    gdown.download(id="154JgKpzCPW82qINcVieuPH3fZ2e0P812", output=os.path.join(parse, "79999_iter.pth"), quiet=True)
    urllib.request.urlretrieve("https://download.pytorch.org/models/resnet18-5c106cde.pth", os.path.join(parse, "resnet18-5c106cde.pth"))


image = (
    modal.Image.debian_slim(python_version="3.11")  # MuseTalk recommends 3.10, which Modal's image builder no longer offers; torch 2.0.1 has 3.11 wheels
    .apt_install("git", "ffmpeg", "libgl1", "libglib2.0-0", "build-essential")
    .pip_install("torch==2.0.1", "torchvision==0.15.2", "torchaudio==2.0.2", index_url="https://download.pytorch.org/whl/cu118")
    .pip_install(  # MuseTalk's requirements.txt without tensorflow, tensorboard and gradio (the server does not use them), plus the web server
        "diffusers==0.30.2", "accelerate==0.28.0", "numpy==1.23.5", "opencv-python==4.9.0.80", "soundfile==0.12.1",
        "transformers==4.39.2", "huggingface_hub==0.30.2", "librosa==0.11.0", "einops==0.8.1", "omegaconf",
        "ffmpeg-python", "moviepy", "imageio[ffmpeg]", "gdown", "requests", "openmim",
        "fastapi==0.115.6", "uvicorn[standard]==0.34.0", "python-multipart",
    )
    .run_commands(f"git clone --depth 1 https://github.com/TMElyralab/MuseTalk {MUSE}")
    .run_commands("mim install mmengine", 'mim install "mmcv==2.0.1"', 'mim install "mmdet==3.1.0"')
    .run_commands("pip install setuptools wheel", "pip install --no-build-isolation chumpy")  # mmpose's chumpy imports pip in its setup.py, absent from pip's isolated build env
    .run_commands('mim install "mmpose==1.1.0"')
    .run_commands('pip install "numpy==1.26.4"')  # mmpose's dependencies pull in numpy 2, which the pinned opencv-python (built for numpy 1) cannot load
    .run_function(download_weights)
    .add_local_file(ROOT / "scripts" / "musetalk_server.py", f"{ARIA}/musetalk_server.py")
    .add_local_file(ROOT / "interface" / "avatar" / "office-wide-glasses.webp", f"{ARIA}/office-wide-glasses.webp")
    .add_local_file(ROOT / "interface" / "avatar" / "presenter-lipsync.mp4", f"{ARIA}/presenter-lipsync.mp4")
)


SERVER = ["python", "-u", f"{ARIA}/musetalk_server.py", "--source", f"{ARIA}/office-wide-glasses.webp",
          "--source-video", f"{ARIA}/presenter-lipsync.mp4", "--host", "0.0.0.0", "--port", "8010"]
SERVER_ENV = {"MUSETALK_DIR": MUSE, "PYTHONIOENCODING": "utf-8"}
FUNCTION = dict(image=image, gpu=GPU, secrets=[modal.Secret.from_name("aria-lipsync")], volumes={f"{MUSE}/results": cache})


# ponytail: one GPU shares a few sessions in arrival order (the server serialises the GPU); past target_inputs Modal adds a GPU, up to MAX_CONTAINERS.
@app.function(**FUNCTION, scaledown_window=IDLE_SECONDS, max_containers=MAX_CONTAINERS, timeout=60 * 60)
@modal.concurrent(max_inputs=6, target_inputs=3)
@modal.web_server(8010, startup_timeout=15 * 60)  # models + both avatars are prepared before the port opens
def serve():
    subprocess.Popen(SERVER, env={**os.environ, **SERVER_ENV})


@app.function(**FUNCTION, timeout=20 * 60)
def debug():
    """modal run deploy/modal_lipsync.py::debug : start the server in the foreground, show its output, and ask it for /health once ready."""
    import hmac
    import time
    import urllib.request

    import io
    import wave

    import numpy as np

    print("GPU:", subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip(), flush=True)
    p = subprocess.Popen(SERVER, env={**os.environ, **SERVER_ENV}, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    def call(path, body=None):
        exp = str(int(time.time()) + 600)
        tok = f"{exp}.{hmac.new(os.environ['ARIA_LIPSYNC_SECRET'].encode(), exp.encode(), 'sha256').hexdigest()}"
        req = urllib.request.Request("http://127.0.0.1:8010" + path, data=body, headers={"x-aria-token": tok}, method="POST" if body else "GET")
        t = time.time()
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
            return r.status, len(data), round(time.time() - t, 1), dict(r.headers)

    for line in p.stdout:
        print(line, end="", flush=True)
        if "MuseTalk ready" in line:
            break
    for _ in range(30):  # the port opens a moment after "ready"
        try:
            print("HEALTH:", call("/health")[:3], flush=True)
            break
        except OSError:
            time.sleep(1)
    t = np.arange(48000) / 16000  # 3 s of speech-like audio: a voiced tone with syllable-rate loudness
    wav = io.BytesIO()
    with wave.open(wav, "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(16000)
        w.writeframes((np.sin(2 * np.pi * 180 * t) * (0.3 + 0.3 * np.sin(2 * np.pi * 4 * t)) * 20000).astype("<i2").tobytes())
    status, size, secs, headers = call("/lipsync_video?avatar=video&fps=15", wav.getvalue())
    print(f"LIPSYNC_VIDEO: status {status}, {size} bytes in {secs}s for 3 s of audio, X-Render-S={headers.get('X-Render-S')}", flush=True)
    p.terminate()
    print("done")
