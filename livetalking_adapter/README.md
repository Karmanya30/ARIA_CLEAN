# LiveTalking adapter (ARIA 6th chat mode)

Runs upstream [LiveTalking](https://github.com/lipku/LiveTalking) (Apache-2.0) as a local service on `127.0.0.1:8020`
with ARIA's Piper voice. ARIA only ever calls `POST /human {type:'echo'}`: its own pipeline writes the text; LiveTalking's
online TTS and LLM are never used. No cloud, no external ICE servers.

## Files
- `piper_tts.py` Piper TTS plugin (`@register("tts","piper")`). Default voice `models/tts/piper/en_US-kristin-medium.onnx` (public domain; do not default to hfc_female / ryan, non-commercial). Sentence streaming, 16 kHz float32, 320-sample chunks, `start`/`end` events as upstream's edge plugin. `flush_talk()` is checked per chunk and per sentence. Missing voice raises `FileNotFoundError` naming the path.
- `serve.py` chdir to `LIVETALKING_DIR`, sets sys.path/PYTHONPATH (spawn children inherit it), applies the two patches below, adds `GET /health`, runs upstream `app.py` via `runpy` behind an `__main__` guard.
- `livetalking.yaml` wav2lip / wav2lip256_avatar1 / port 8020 / stun '' / max_session 2 / batch 8 / tts piper / webrtc / 25 fps.
- `upstream.patch` the two upstream edits (applied idempotently by `serve.py`, so a fresh clone needs nothing manual): `avatars/base_avatar.py` TTS table gets `'piper': 'livetalking_adapter.piper_tts'` (the table is a local dict inside `BaseAvatar.__init__`, runtime injection is impossible, risk R5); `app.py` binds `LT_BIND` (default `127.0.0.1`) instead of `0.0.0.0`.
- `smoke.py` aiortc client: offer/answer, echo, first-audio time, interrupt.
- `../scripts/start_livetalking.bat`, `../tests/livetalking/`.

## Start
`scripts\start_livetalking.bat` (logs `logs\livetalking.out.log` / `.err.log`; exit 2 with a message if env, checkout, `models\wav2lip.pth`, avatar dir or voice is missing).
Knobs (env vars): `LIVETALKING_DIR` (E:\LiveTalking\src; env python is `..\env\python.exe`), `LT_MODEL`, `LT_AVATAR`, `LT_VOICE`, `LT_PORT`, `LT_BATCH`, `LT_BIND`.
Ready when `GET http://127.0.0.1:8020/health` returns `{"ready":true,"model","avatar","sessions"}`; the port does not listen until models are loaded.

## API used
`GET /health`, `POST /offer {sdp,type}` -> `{sdp,type,sessionid}`, `POST /human {sessionid,text,type:'echo',interrupt}`, `POST /interrupt_talk {sessionid}`, `POST /is_speaking`.

## Tests
`E:\LiveTalking\env\python.exe -m pytest tests/livetalking` (fake parent: chunk shape/dtype, events, flush mid-text, missing voice, real kristin voice). In ARIA's own env the module skips.
Live check: start the service, then `E:\LiveTalking\env\python.exe livetalking_adapter\smoke.py`.

## Rollback
Delete nothing in ARIA: stop the process, or `ARIA_LIVETALKING=0` in the launcher. To undo the upstream edits: `git -C E:\LiveTalking\src checkout app.py avatars/base_avatar.py`.

## Fresh checkout

A fresh LiveTalking clone needs the full patch once (serve.py re-applies only two of its edits; the interrupt fix is in the patch): `cd E:\LiveTalking\src && git apply E:\ARIA\livetalking_adapter\upstream.patch`. The checkout on this PC is already patched. Details and measured numbers: BENCHMARKS.md.
