# LiveTalking models, avatar and install (local-only; nothing here is committed except this file)

Installed outside the repo under `E:\LiveTalking` (about 0.56 GB source+data, 5.4 GB env, plus `dl\` download copies 0.55 GB that can be deleted).

| Item | Where | Details |
|---|---|---|
| LiveTalking source | `E:\LiveTalking\src` | https://github.com/lipku/LiveTalking, **pinned commit `c7269433a2b6ecebcd9342445d2ecc882c98b0da`** (2026-10-20). Apache-2.0. Local patches: `upstream.patch` (this folder, `git diff` against that commit). |
| Python env | `E:\LiveTalking\env` | conda Python 3.12 (no fallback needed), torch 2.9.1+cu128, torchvision 0.24.1, torchaudio 2.9.1, `requirements.txt`, piper-tts 1.8.0, onnxruntime 1.31, gdown, plus for the optional MuseTalk avatar generation `dlib-bin`, `face_recognition`, `face_recognition_models`, `setuptools<81`. Frozen list: `requirements-lock.txt`. torch.cuda.is_available() is True (RTX 4060 Laptop 8 GB). `E:\MuseTalk\env` was never touched. |
| Caches | `E:\LiveTalking\cache\{pip,conda,hf,torch}`, `E:\LiveTalking\tmp` | C: stayed at 2.9 GB free. |

## Weights and avatars
| File | Path | SHA256 | Size | Source / licence |
|---|---|---|---|---|
| wav2lip256.pth (as `models\wav2lip.pth`) | `E:\LiveTalking\src\models\wav2lip.pth` | `b22d7ac86295df667644b17254dc71250c2600b89e20403e90e58812450bc173` | 214,670,409 | LiveTalking README Google Drive folder (`1FOC_MD6wdogyyX_7V1d4NDIO7P9NlSAJ`), downloaded with gdown (worked, no manual step). Wav2Lip lineage: **non-commercial research** use. |
| wav2lip256_avatar1.tar.gz | `E:\LiveTalking\dl\` -> `src\data\avatars\wav2lip256_avatar1` (550 frames, 576x768) | `8e8c82bf973b91db799ed8b557d1b869438e094bcd1b0cf0bd72b208d5329369` | 353,005,497 | Same Drive folder. **No licence, provenance or model release**: local personal/demo use only; never commit, never put under `E:\ARIA`; credit it in the UI. |
| musetalk_sample avatar | `src\data\avatars\musetalk_sample` | generated here (150 frames of the sample face, MuseTalk preprocessing `avatars.musetalk.genavatar`) | - | Derived from the sample face: same restrictions. Benchmark only. |

Junctions (not copies) in `E:\LiveTalking\src\models`: `musetalkV15`, `sd-vae`, `whisper`, `dwpose`, `face-parse-bisent` -> `E:\musetalk\MuseTalk\models\<same name>`. Files > 1 MB:

| File (under E:\musetalk\MuseTalk\models) | SHA256 | Size | Licence |
|---|---|---|---|
| musetalkV15\unet.pth | `7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007` | 3,400,074,924 | MuseTalk (MIT code; weights per the MuseTalk repo terms) |
| sd-vae\diffusion_pytorch_model.bin | `1b4889b6b1d4ce7ae320a02dedaeff1780ad77d415ea0d744b476155c6377ddc` | 334,707,217 | sd-vae-ft-mse, CreativeML OpenRAIL-M |
| whisper\pytorch_model.bin | `9607f98a2b22d9e229ae43c52ecea79dcede9e0c5cfae67e8da6eda86d8aac1d` | 151,095,027 | Whisper tiny, MIT |
| dwpose\dw-ll_ucoco_384.pth | `0d9408b13cd863c4e95a149dd31232f88f2a12aa6cf8964ed74d7d97748c7a07` | 406,878,486 | DWPose, Apache-2.0 |
| face-parse-bisent\79999_iter.pth | `468e13ca13a9b43cc0881a9f99083a430e9c0a38abd935431d1c28ee94b26567` | 53,289,463 | BiSeNet face parsing, MIT |
| face-parse-bisent\resnet18-5c106cde.pth | `5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8` | 46,827,520 | torchvision ResNet18, BSD-3 |

Voice: Piper `en_US-kristin-medium` (public domain), see the plan. Not downloaded by this work.

## Reproduce
`conda create -p E:\LiveTalking\env python=3.12`, `pip install torch==2.9.1 torchvision==0.24.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128`, `pip install -r src\requirements.txt piper-tts==1.8.0 onnxruntime gdown`, set `PIP_CACHE_DIR/TEMP/TMP/HF_HOME` to E: first. Download with `gdown --folder <Drive URL>`. Apply `upstream.patch` with `git apply` in `src` (see BENCHMARKS.md for what it contains). MuseTalk avatar generation needs `PYTHONPATH=src\avatars\musetalk\utils;src` so the bundled `face_detection` is found.
