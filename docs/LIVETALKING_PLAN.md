# Plan: ARIA 6th chat mode "LiveTalking Avatar (Local)"

Planned by the planning agent (Opus), 21 Oct 2026. Implementation by Sonnet agents (medium effort). Progress: docs/LIVETALKING_PROGRESS.json.

## Decisions
- Mode label: `'LiveTalking Avatar (Local)'` (sixth chat mode; the fifth, 'Local Avatar (Live Face)', is the in-house MuseTalk avatar_engine on port 8010 and keeps working).
- Service: LiveTalking (github.com/lipku/LiveTalking, Apache-2.0) on **port 8020** (its default 8010 collides with avatar_engine; the launcher scans 8000..8019 for the API). Own env at `E:\LiveTalking\env` (Python 3.12, torch 2.9.1 cu128): the pins are incompatible with `E:\MuseTalk\env` (torch 2.0.1 cu118), which must not be touched.
- Face: the sample avatar the LiveTalking README recommends (`wav2lip256_avatar1`, optional `musetalk_avatar1`). Not ARIA's default face, not the Tavus replica, not any user-supplied face. The sample has **no licence/provenance/model release**: local personal/demo use only; never commit it; keep it under `E:\LiveTalking`; credit it in the UI.
- Default model: Wav2Lip256 (README asks for a 3080Ti+ for MuseTalk; this GPU is an RTX 4060 Laptop 8 GB). MuseTalk-in-LiveTalking is a benchmarked option only. `wav2lip256.pth` is non-commercial lineage.
- Voice: Piper `en_US-kristin-medium` (LibriVox, public domain, already on disk). Rejected: hfc_female, ryan (CC BY-NC-SA), lessac (restrictive). NOTE for the user: avatar_engine's current default voice (hfc_female-medium) is CC BY-NC-SA: flag it, do not change it in this task.
- Only `POST /human {type:'echo'}` is used: ARIA's own pipeline produces the text; LiveTalking's online TTS (edgetts) and its LLM (`type:'chat'`) are never used. Ongoing cost 0.
- C: has ~3.2 GB free: redirect every cache to E: (PIP_CACHE_DIR, CONDA_PKGS_DIRS, TEMP/TMP, HF_HOME under E:\LiveTalking\...). E: has ~150 GB. Total need ~15 GB.

## Architecture
Browser -> POST /api/chat (mode only changes presentation) -> modules/qa/pipeline.answer() -> reply -> ChatTab setLastReply -> LiveTalkingPanel (spokenFor: reply.spoken | /api/chat/spoken | conciseSpoken) -> POST /livetalking/human {sessionid, text, type:'echo', interrupt:true} (vite proxy -> 127.0.0.1:8020) -> LiveTalking :8020 (Piper TTS plugin -> Wav2Lip256 on the GPU -> aiortc H264/VP8 + Opus on one WebRTC connection) -> <video> in the panel. Fallback to the VoiceDisk with a notice when the service is down/busy. Barge-in: composer input and `aria:voice-capture-start` events plus a Stop button call /interrupt_talk. Rollback: `ARIA_LIVETALKING=0` (GPU launcher skips the service) or one `git revert` of the separate 'wire 6th mode' commit.

## Work packages (weights sum 100)
| WP | Weight | Scope | Owner |
|---|---|---|---|
| WP0 Disk/env prep | 4 | caches to E:, dirs under E:\LiveTalking | A |
| WP1 LiveTalking install | 12 | clone (pin commit), conda py3.12 env, torch 2.9.1 cu128, requirements, piper-tts, lock file | A |
| WP2 Weights + sample avatar | 8 | wav2lip256.pth -> models/wav2lip.pth, wav2lip256_avatar1, junctions to MuseTalk 1.5 weights, SHA manifest (livetalking_adapter/MODELS.md) | A |
| WP3 Service adapter | 14 | livetalking_adapter/{serve.py,piper_tts.py,livetalking.yaml}, scripts/start_livetalking.bat, optional /health | B |
| WP4 Benchmark | 10 | first-audio/first-video latency, fps, lip-sync lag, interruption, VRAM, coexistence with avatar_engine; LiveTalking-Wav2Lip vs MuseTalk vs avatar_engine; decide default | A |
| WP5 Front end | 16 | web/src/components/livetalking/{useLiveTalking.ts,LiveTalkingPanel.tsx,css}; export spokenFor | C |
| WP6 Shared-file wiring | 6 | ChatMode in 3x types.ts, MODES in 3x ChatTab.tsx, vite proxy /livetalking, modules/qa/models.py enum; re-read before every edit; separate commit | C (web) / D (enum) |
| WP7 Launchers | 14 | scripts/aria_launcher.ps1 LiveTalking block (flags ARIA_LIVETALKING, ARIA_GPU_AVATARS, LIVETALKING_DIR; port check, missing-file check, VRAM gate, sequential start, health wait, logs, visible problems), test matrix of 12 scenarios for Launch_ARIA.bat and Launch_ARIA.bat gpu | D |
| WP8 Tests | 9 | tests/livetalking, tests/qa mode param, Playwright/CDP checks, scripted launcher smoke | B/C/D |
| WP9 Docs + licensing | 7 | livetalking_adapter/README.md, THIRD_PARTY_NOTICES.md, rollback rehearsal | D |

Percent done = sum of weights of finished WPs, plus half the weight of a WP whose code is written but whose acceptance test is still open.

## Acceptance targets (default model)
first-audio <= 1.2 s, first-video <= 1.2 s (short text), steady 25 fps with 0 freezes over the 16 s paragraph, lip-sync lag <= 80 ms, interruption <= 0.5 s, process VRAM <= 2.5 GB (Wav2Lip) so it can coexist with avatar_engine (or <= 5 GB if MuseTalk is default; then only one loads).

## Launcher test matrix (both launchers: N = Launch_ARIA.bat, G = Launch_ARIA.bat gpu; also the 'Launch ARIA (Lip-sync GPU)' shortcut and `Start-Process aria://launch-gpu`)
1 cold start; 2 rerun while up (idempotent, no duplicates); 3 another app (Bhauly) holds 8000 -> API 8001; 4 foreign app holds 8020 -> warning, fallback, exit 0; 5 env/weights missing -> warning lists paths; 6 ARIA_LIVETALKING=0 -> identical to today; 7 low free VRAM -> LiveTalking skipped with message, no OOM; 8 LiveTalking crashes at start -> 'exited early' + err-log tail within 10 s; 9 engine up, LiveTalking not -> only LiveTalking starts; 10 two launchers at once -> mutex, one instance; 11 ARIA_GPU_AVATARS=livetalking|engine; 12 outdated API revision -> API restarted, GPU services not.

## Risks and fallbacks
R1 MuseTalk < 25 fps on the 4060 Laptop -> Wav2Lip default; TAESD / lower-face decode patch; keep MuseTalk quality in the fifth mode. R2 Wav2Lip softness -> small bust framing, no upscaling. R3 Windows install failure -> Python 3.11 + matching torch, else WSL2. R4 musetalk_avatar1 only on Xunlei/Quark -> generate from the same sample face in a throwaway env or drop the arm. R5 Piper plugin injection fails under spawn -> tracked one-line upstream.patch or /humanaudio route. R6 WebRTC mDNS candidates/autoplay -> 127.0.0.1 page, 'click to enable sound'. R7 VRAM/RAM -> sequential load, free-VRAM gate, max_session 2, batch 8. R8 licences -> local use only, watermark if recordings are published, swap in a consented face if ever commercial. R9 conflicts with the QA-unification agent -> shared-file edits last, re-read first. R10 C: exhaustion -> cache redirection, check before every step. R11 upstream churn -> pin commit, keep lock file.

## Parallel agents and file ownership
A Install & benchmark (WP0,1,2,4): everything under E:\LiveTalking\, livetalking_adapter/{bench.py,BENCHMARKS.md,MODELS.md,requirements-lock.txt}; never edits E:\MuseTalk\env.
B Service adapter (WP3, WP8a): livetalking_adapter/{__init__,serve,piper_tts}.py, livetalking.yaml, scripts/start_livetalking.bat, tests/livetalking/.
C Front end (WP5, WP6 web, WP8c): web/src/components/livetalking/*, one-keyword export in AvatarStage.tsx; at the end the three types.ts, three ChatTab.tsx, vite.config.ts (re-read first).
D Launchers/backend enum/docs (WP7, WP6 enum, WP8b/d, WP9): scripts/aria_launcher.ps1, Launch_ARIA.bat comment, THIRD_PARTY_NOTICES.md, scripts/README.md, modules/qa/models.py ChatMode value, tests/qa/test_unified_pipeline.py one line.
Interface agreed between B and D: scripts\start_livetalking.bat, port 8020, health probe /health (or /index.html), process match `livetalking_adapter.serve`.
