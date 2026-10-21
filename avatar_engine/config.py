"""Paths and tuning knobs (all overridable with environment variables)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(os.getenv("AVATAR_DATA_DIR", ROOT / "data" / "avatar"))
REPLICA_DIR = DATA_DIR / "replicas"
SAMPLE_DIR = DATA_DIR / "samples"
LOG_DIR = ROOT / "logs"
DEFAULT_FACE = ROOT / "interface" / "avatar" / "face.png"
VOICE_DIR = ROOT / "models" / "tts" / "piper"
MODEL_DIR = ROOT / "models" / "avatar"
MUSETALK_DIR = Path(os.getenv("MUSETALK_DIR", r"E:\MuseTalk\MuseTalk"))

PORT = int(os.getenv("AVATAR_PORT", "8010"))
BACKEND = os.getenv("AVATAR_BACKEND", "musetalk")        # musetalk | fake (tests, no GPU)
DISPLAY_FPS = int(os.getenv("AVATAR_FPS", "25"))          # frames per second sent to the browser
MOUTH_FPS = int(os.getenv("AVATAR_MOUTH_FPS", "20"))      # lip-sync frames generated per second of speech (12..25)
BATCH = int(os.getenv("AVATAR_BATCH", "8"))               # frames per GPU batch: small = earlier first frame
VAE_MODE = os.getenv("AVATAR_VAE", "half")                # half (real VAE, lower face only) | full | taesd (fastest, softer)
VOICE = os.getenv("AVATAR_VOICE", "en_US-hfc_female-medium")
OUT_W, OUT_H = int(os.getenv("AVATAR_W", "512")), int(os.getenv("AVATAR_H", "512"))
JPEG_QUALITY = int(os.getenv("AVATAR_JPEG_Q", "85"))
MAX_VIDEO_FRAMES = int(os.getenv("AVATAR_MAX_VIDEO_FRAMES", "150"))
EDGE_FALLBACK = os.getenv("AVATAR_EDGE_FALLBACK", "0") == "1"  # online Edge-TTS only if Piper is unavailable
