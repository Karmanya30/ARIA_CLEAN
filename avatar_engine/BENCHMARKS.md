# Lip-sync backend benchmarks (this PC)

Machine: RTX 4060 Laptop GPU (8188 MiB, driver 596.08), Windows 11, 22 logical CPUs, ~15 GB RAM (mostly in use by other
jobs during the runs), MuseTalk env = Python 3.10, torch 2.0.1+cu118, fp16. Test input: `interface/avatar/face.png`
(1080x1440 portrait; still image) and, for the video path, MuseTalk's `data/video/yongen.mp4` (first 150 frames);
speech = Piper audio (3.5 s greeting, 16.3 s paragraph). No microphone is used anywhere. Scripts: `avatar_engine/bench/`.

## Summary table

"GPU fps" = lip-sync frames generated per second of wall time on the GPU thread (steady state, 16 s of speech, batch 8),
without the CPU compositing/JPEG (about 15 ms per output frame, done on other threads in parallel). "First batch" = audio in ->
first 8 mouth frames on the CPU. VRAM = memory reserved by the process (nvidia-smi for the whole card in brackets).

| Backend (face size) | GPU fps | First batch | VRAM | Visual quality (looked at frames) | Verdict |
|---|---|---|---|---|---|
| **MuseTalk 1.5, stock full VAE decode, 256 px face** | 19.9 (UNet ~10 ms + VAE 37 ms per frame) | 0.41 s | 4.3 GB (5.5 GB card) | Best: sharp lips and teeth, natural skin | Just under 25 fps real time: not enough margin |
| **MuseTalk 1.5, lower-face VAE decode ("half") - CHOSEN** | **27.1** | **0.31 s** | 3.7 GB (4.8 GB card) | Same as full (side-by-side checked: no visible seam; decodes latent rows 12-31 and splices below face row 128) | Chosen: 1.08x real time at 25 mouth fps, 1.35x at 20 mouth fps |
| MuseTalk 1.5, TAESD tiny decoder | 64.3 | 0.16 s | 2.9 GB (4.1 GB card) | Good mouth, but skin looks airbrushed/soft | Option `AVATAR_VAE=taesd`; also the automatic OOM/slow downgrade |
| Wav2Lip GAN (96 px face) | 474 / 597 / 737 at batch 8 / 16 / 32 (model only, incl. copy to CPU) | ~0.05 s (est.) | 0.32 GB peak | Clearly worse: blurry lower face at 96 px upsampled to ~450 px, small mouth movement | Not used. Fastest by far; quality is not usable at this display size |
| LivePortrait | not measured | - | - | - | Not audio-driven (it re-targets a driving video/expressions); heavy install, so not used. It would be the next step for richer head/expression motion, not for lip-sync |

Notes on honesty:
* Wav2Lip was measured at model level only (mel -> 96 px face, `bench_wav2lip.py` in `E:\avatar_bench`, not kept in the repo); it was not wired into the full pipeline. Its face crop was MuseTalk's detector box.
* MuseTalk numbers are end-to-end through `MuseTalkBackend.lipsync` (`bench/try_backend.py`): features (Whisper-tiny) + UNet + VAE + GPU->CPU copy.
* Raw stock MuseTalk via the old `scripts/musetalk_server.py` was documented as ~15 fps at ~1.05x real time (its own comment); the new backend removes autograd graphs, caps the cuDNN workspace and decodes only the half of the face the model changes.
* Per-component (bench_musetalk.py / bench_vae.py): Whisper-tiny features 45-85 ms per call (fixed 30 s window, so cost does not depend on clip length); UNet 15.5 / 11.5 / 10.2 / 10.0 ms per frame at batch 4 / 8 / 12 / 16; SD-VAE decode 36.5-38 ms per frame (flat in batch size, channels_last does not help); lower-rows decode 20.7-21.3 ms; TAESD 3.4 ms.
* An early run showed the VAE decode collapsing to 4-25 s per batch when the process spilled over 8 GB (WDDM paging): cuDNN workspace growth filled the card (7.8 GB reserved for the same job). `set_per_process_memory_fraction(0.6)` + contiguous latents fixed it (3.7 GB, no loss of speed).

## Full pipeline (engine running, WebSocket, 512x512 output, mouth 20 fps, voice hfc_female-medium)

From `scripts/avatar_engine_smoke.py` (default replica; client-side numbers, so they include the network hop to localhost):

| Utterance | Time to first speech frame | Video fps while speaking | Underruns | VRAM (whole card) |
|---|---|---|---|---|
| "Hello, I am ARIA, your financial companion." (3.2 s) | 1.0-1.07 s | 25.0 | 0 | 3.8 GB (peak 3.8) |
| 16 s paragraph (first clause cut to ~36 chars) | 1.5-1.8 s | 25.0 | 0 | 3.8 GB |
| interrupt 1.2 s into speech | `idle` event 0-2 ms after the message, no audio afterwards | - | - | - |

Where the 1.0 s goes: Piper ~0.17 s (medium voice; `cori-high` ~0.3-0.7 s) + resample/queue ~0.05 s + first batch 0.31 s + waiting until the frames generated so
far can play without running dry (the engine starts a clause once `frames_ready/mouth_fps >= frames_left/gen_fps + 0.08 s`).
The ~1.5 s paragraph figure is longer because its first clause is long; `AVATAR_VAE=taesd` brings both close to 0.6-0.7 s at a cost in skin texture.
A video replica (yongen, 298 ping-pong frames): same fps and first-frame time, but 10 underruns on the paragraph (generation briefly slower while the other job on the PC was busy) -> the engine lowers the lip-sync rate for the next utterance.

Replica creation: photo ~10 s (DWPose + face detection + parsing + matte, first run also loads them), 150-frame video ~53 s.
Engine start to ready: 37-45 s with cached replica (model load ~18 s, warm-up ~10 s).
