# ARIA local avatar engine

A self-hosted "Tavus-like" talking avatar: no cloud API, no paid keys, nothing leaves the PC. It speaks the text it is
given (ARIA's answers still come from the brain, i.e. Groq) and streams **lip-synced video frames + audio** over a
WebSocket. Port **8010**, localhost only.

```
text ──► split (first piece short) ──► Piper TTS (CPU) ──► MuseTalk 1.5 lip-sync (GPU, fp16) ──┐
                                                                                                ▼
 photo/video "replica" (face crop, landmarks, latents, masks cached on disk)  ──►  compositor (CPU: idle pose, blink,
                                                                                    gaze, brows, smile, mouth patch,
                                                                                    framing, background) ──► JPEG/WebP
 25 fps render loop on the wall clock ──► WebSocket: video frames + 16-bit PCM audio, same timestamps
```

* `server.py` FastAPI app (HTTP + WebSocket). `session.py` one live session: render loop + speech pipeline.
* `backend_musetalk.py` GPU backend (MuseTalk 1.5, fp16, lower-face VAE decode, OOM handling). `backend_fake.py` GPU-free stand-in for tests.
* `compositor.py` / `expressions.py` / `motion.py` everything the browser sees besides the generated mouth.
* `replicas.py` replica store on disk. `tts.py` Piper (Edge-TTS only as opt-in fallback). `chunking.py` text splitting. `protocol.py` binary framing.
* `BENCHMARKS.md` measured numbers and why MuseTalk 1.5 was chosen. `bench/` the scripts behind them.

## Start

```
scripts\start_avatar_engine.bat        # ~40 s to load + warm up, then /health says ready
powershell scripts\restart_avatar_engine.ps1 [half|taesd]   # dev helper: restart this engine only
```

`aria://launch-gpu` (scripts/aria_launcher.ps1) now starts this engine instead of the old `musetalk_server.py`
(`logs\avatar_engine.out.log`, `logs\avatar_engine.err.log`, `logs\avatar_engine.log`). It runs in the MuseTalk
python environment (`E:\MuseTalk\env`, Python 3.10, torch 2.0.1+cu118); `piper-tts`, `onnxruntime`, `websockets`,
`python-multipart`, `loguru` were added to that environment. A browser demo/reference client is served at
`http://127.0.0.1:8010/demo`.

## API

**GET /health** -> `{status: ok|starting|error, ready, detail, backend, vae_mode, gpu, vram_used_mb (whole card), process_vram_mb, fps, gen_fps, mouth_fps, replica_default, session_active, voices, default_voice, last_metrics}`

**Replicas** (a replica = one person/face; face detection, 68 landmarks, crop, VAE latents, blend masks, person matte are
computed once and cached in `data/avatar/replicas/<id>/`):
* `POST /replicas` multipart `file` (or `image`) = photo (png/jpg/webp) or short video (mp4/mov/webm, first 150 frames
  at <=25 fps are used), optional `name` -> `{id, replica_id, name, kind, face_box, size, frames, matte, preview_url}`.
  Photo ~10 s, 6 s video ~50 s (blocks the GPU meanwhile). Errors: 400 (no face / bad file), 413, 503 (not ready).
* `GET /replicas`, `DELETE /replicas/{id}` (the `default` replica and the replica of a live session cannot be deleted), `GET /replicas/{id}/preview` (JPEG).
* `default` is built from `interface/avatar/face.png` on first start.

**WebSocket `/stream?replica_id=default&w=512&h=512&framing=bust|face|full&bg=original|blur|transparent|%23rrggbb&takeover=0&speak_id=`**

Client -> server (JSON text):
| message | effect |
|---|---|
| `{type:'speak', text, voice?, emotion?, style?}` | `voice`: a Piper voice name, `aria` (default) or `edge:<ShortName>`; `emotion`: neutral/warm/serious/concerned/upbeat; `style: {rate: 0.9}` speaking-rate multiplier. Several speaks queue up. |
| `{type:'interrupt'}` | everything stops, `state:idle` is sent immediately (measured: ~1-2 ms server side), generation stops at the next 8-frame batch (<= ~0.3 s later, GPU only) |
| `{type:'ping', t}` | `{type:'pong', t, server_ms}` |
| `{type:'listening', value:true|false}` | shows an attentive "listening" pose (`state:listening`); the UI sends it while the user talks |
| `{type:'configure', emotion?, background?, framing?, width?, height?}` | change mood / background / crop / size live |

Server -> client:
* **binary**, 9-byte little-endian header `u8 type | u32 sequence | u32 timestamp_ms` (stream clock, ms since the socket opened):
  * type `1` video: JPEG (WebP when `bg=transparent`, because it carries alpha; `createImageBitmap` sniffs both). 25 fps, always (idle frames too).
  * type `2` audio: `u32 sample_rate` + 16-bit signed LE mono PCM (22 050 Hz for Piper). One slice per video tick, timestamps on the same clock.
* **JSON**: `{type:'state', value:'idle'|'thinking'|'speaking'|'listening'|'unavailable', reason?}`, `{type:'caption', text, t_start, t_end}` (ms on the stream clock, one per clause), `{type:'metrics', ttfb_ms, fps, gen_ms, mouth_fps, underruns}` (after each utterance), `{type:'notice', message}` (automatic downgrades), `{type:'error', message}`, `pong`.
* Playback in the browser: `localOffset = performance.now() - ts` of the first message; play frame/audio at `localOffset + ts + ~150 ms` (WebAudio `start(when)`, canvas `drawImageBitmap`). `/demo` is a 90-line working example. On `interrupt` or `idle` stop the queued audio sources.
* **Fallback signal**: `{type:'state', value:'unavailable', reason}` (engine warming up, GPU out of memory with nothing left to downgrade, render error, another session active, replica missing) followed by a close -> the UI should show its audio-reactive disk.
* One live session at a time. A second connection is refused with `unavailable` ("busy: ...") unless it passes `takeover=1`, which closes the old one (useful for page reloads / React dev double mounts).

**POST /speak** `{text, voice?, emotion?, style?, replica_id?}` -> `{id, stream_url, expires_s}`; open `stream_url` as the WebSocket within 30 s and the speech starts at once.

## Idle behaviour and presets
Frames never freeze: sway (a few px, <1 degree), breathing, blinks every ~3-4 s (12 % double blinks), eye saccades, and while speaking
extra head/brow emphasis driven by the audio loudness. Blink/gaze/brow/smile are local warps on the 68 landmarks (photos only; a
video replica plays its own motion, ping-pong looped, with the mouth patched in).
Emotion presets change head tilt/nod, sway amplitude, blink rate, brow height/inner brow and smile. **Honest limits:** the effect is
subtle (a few pixels), MuseTalk has no style conditioning so the *generated mouth* is identical across presets, and `smile` only shows
on idle frames (the generated mouth replaces that region while speaking). The speaking rate does change per preset (Piper `length_scale`).
Backgrounds use a one-time U2Net human-segmentation matte (photos only): hair edges can show a faint halo.

## Robustness
* Models are loaded and the whole speech path is warmed up (twice) at startup; `/health.ready` is false until then.
* CUDA OOM: batch halves and retries; if it still fails the decoder switches to TAESD and the lip-sync rate drops 25->20->15->12 fps with a `notice`; if nothing is left: `state:unavailable`. Allocator cap `AVATAR_VRAM_FRACTION=0.6` (4.9 GB) stops cuDNN workspaces from filling the 8 GB card (measured: 7.8 GB reserved without the cap, 3.7 GB with).
* Generation slower than real time (underruns) lowers the lip-sync rate for the next utterance.
* Disconnect / `takeover` / interrupt cancel TTS, generation and playback; GPU work stops at the next batch.
* All GPU work runs on one thread (cuDNN keeps per-thread workspaces), TTS on another, compositing on two.

## Tuning knobs (environment variables)
`AVATAR_PORT` (8010), `AVATAR_MOUTH_FPS` (20; lip-sync frames per second of speech, 12-25, the display is always 25 fps and the mouth is cross-faded),
`AVATAR_VAE` (`half` default | `full` | `taesd`: 2.4x faster, softer skin), `AVATAR_BATCH` (8), `AVATAR_VOICE` (`en_US-hfc_female-medium`; `en_GB-cori-high` is higher quality but ~4x slower to synthesise),
`AVATAR_W/H` (512x512), `AVATAR_JPEG_Q` (85), `AVATAR_VRAM_FRACTION` (0.6), `AVATAR_BACKEND=fake` (no GPU), `AVATAR_EDGE_FALLBACK=1` (online Edge-TTS if Piper is missing), `MUSETALK_DIR`, `AVATAR_DATA_DIR`.

## Measured on this PC (RTX 4060 Laptop 8 GB, see BENCHMARKS.md)
Steady lip-sync generation ~26-27 frames/s (`half`), output 25 fps at 512x512, time to first video frame **~1.0 s** for a short
greeting and **~1.5 s** for a long paragraph, ~3.8 GB VRAM for the process, interrupt -> idle ~1 ms (+ GPU stops <= ~0.3 s later), 29 kB per JPEG frame (~0.7 MB/s).

## Limits
* Lip-sync quality is MuseTalk's: mouth/jaw only, 256 px face crop (the face is ~190-260 px in a 512 px frame, so teeth look soft); head turns/expressions come only from the idle layer.
* Photos: one frame is looped, so the mouth region must be tolerable as a still; side-on faces or hands over the mouth give artefacts. Videos: use a calm, front-facing, mouth-closed clip of 3-6 s.
* No Indian-English Piper voice exists (en_US/en_GB only); `edge:en-IN-NeerjaNeural` works only with internet and `AVATAR_EDGE_FALLBACK`/explicit `voice`.
* One live session, one GPU job at a time (creating a replica pauses speech for 10-50 s).
* Presets are subtle; no gestures, no eye contact tracking, no real "listening" reaction beyond a pose.
* Engine RAM/VRAM budget assumes nothing else big is on the GPU; the PC was also running other python jobs during the measurements.

## Tests
```
E:\MuseTalk\env\python.exe -m pytest tests/avatar        # 41 tests, ~12 s, fake backend + fake TTS, no GPU, no microphone
.venv\Scripts\python.exe scripts\avatar_engine_smoke.py    # needs the engine running: real GPU run, writes data/avatar/samples/
```
