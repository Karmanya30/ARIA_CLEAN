# LiveTalking benchmarks (this PC)

RTX 4060 Laptop 8 GB, Windows 11, LiveTalking commit `c7269433` + `upstream.patch`, env Python 3.12 / torch 2.9.1 cu128, sample face `wav2lip256_avatar1`
(MuseTalk arm: same face, 150-frame loop generated locally). Service started through `livetalking_adapter.serve` (Piper `en_US-kristin-medium`, text via `POST /human {type:'echo'}`),
client = `bench.py` (aiortc, localhost, no microphone). Five runs per arm, each run = one short sentence ("Hello, I am ARIA...", 3.5 s), one 16 s paragraph, one interruption 3 s into the paragraph.
Cells are median / p90. Raw lines: `E:\LiveTalking\results.jsonl`. One avatar process on the GPU at a time, except the coexistence row.

| Arm | First audio (s) | First video (s) | Video fps (16 s para) | Freezes >200 ms | Interrupt: last audio after request (s) | VRAM (whole card): idle loaded / peak |
|---|---|---|---|---|---|---|
| **Wav2Lip256, batch 8 (final, with flush patch)** | **0.82 / 0.85** | **0.73 / 0.76** | **25.2 / 25.4** | **0 / 0** | **0.32 / 0.39** | **1.3 GB / 1.3 GB** (see note) |
| Wav2Lip256, batch 8, before the flush patch (first run of the arm) | 0.99 / 1.23 | 0.93 / 1.21 | 25.5 / 26.9 | 0 / 1 | 0.82 / 1.42 | 1.3 GB / 2.6 GB (other GPU jobs were active) |
| Wav2Lip256, batch 16 | 1.04 / 2.14 | 0.92 / 2.15 | 25.9 / 26.0 | 0 / 0 | 0.73 / 1.29 | 2.3 GB / 2.3 GB |
| MuseTalk 1.5 inside LiveTalking, batch 8 | 6.1 / 8.3 | 4.8 / 6.1 | **2.5** / 2.9 | 3 / 3 | not meaningful | **7.9 GB** (card full, spills to shared memory) |
| Wav2Lip256 b8 with avatar_engine resident (coexistence) | 0.93 / 3.2 | 0.90 / 3.1 | 25.8 / 27.9 | 0 / 0 | 0.40 / 1.15 | 5.1 GB both idle / 5.2 GB peak |
| avatar_engine (fifth mode, reference; `scripts/avatar_engine_smoke.py`, 1 run, its own protocol) | 1.1 (short) / 1.6 (paragraph) | = first speech frame | 25.0-25.1 | 0 underruns | 0.003 (server `idle` event) | 3.8 GB |

Targets (default model): first audio <= 1.2 s MET (median 0.82, p90 0.85 alone); first video <= 1.2 s MET; 25 fps with 0 freezes MET; interruption <= 0.5 s MET after the flush patch (median 0.32, p90 0.39; 10 further trials ranged 0.0-0.51 s, so a rare trial can sit at the limit); process VRAM <= 2.5 GB MET (about 1.3 GB steady, the 2.6 GB peak in the early row was not LiveTalking: the coexistence row, taken later, shows only +0.1 GB while speaking); lip-sync lag <= 80 ms NOT MEASURED RELIABLY (see below).

## Honest caveats
* **Lip-sync lag is not established.** The cross-correlation between the audio envelope and mouth-ROI change had a correlation of only 0.06-0.28 (Wav2Lip's mouth change is small against H.264 noise), so the lag values (-200..+430 ms) are noise. By construction audio and video frames of one batch leave the same queue and are paced by the same 25 fps clock, so the sender-side offset should be about one frame; first-video minus first-audio was -0.1 s (video activity detected slightly before audio, within detector noise). A real check needs a sync-test clip (clap/flash) or a human look.
* Times are client arrival times on localhost; the first-video detector compares the mouth ROI with the nearest idle-loop frame (threshold idle mean + 6 sd + 1), a proxy.
* The coexistence p90 (3.2 s first audio) comes from one run where the GPU was shared with the idle-but-resident engine and the other agents' processes; median is unaffected. Re-run when the machine is quiet if this matters.
* avatar_engine row is the existing smoke script (one run, different protocol), not 5 runs of bench.py.
* The earlier interrupt numbers (0.8 s, also seen by Agent B's smoke) were mostly speech already rendered ahead in the pipeline; upstream only cleared the TTS/ASR input queue.

## Upstream patch (`upstream.patch`, `git diff` against the pinned commit)
Contains Agent B's two edits (`piper` in the TTS table, `LT_BIND`) plus the interrupt fix: `HumanPlayer.flush()` (drop queued audio+video), `BaseAvatar.flush_talk` (also clears `res_frame_queue`, turns speech frames waiting in `asr.output_queue` into silence, bumps a flush generation so the batch already being inferred is sent as idle frames). `serve.py` re-applies only B's two edits as text patches; the flush part is already in `E:\LiveTalking\src`. On a fresh clone: `cd E:\LiveTalking\src && git apply ..\..\ARIA\livetalking_adapter\upstream.patch` (apply once, instead of serve.py's patches).

## Decision
* **Default: Wav2Lip256, batch 8** (`LT_BATCH=8`, as in `start_livetalking.bat`). Batch 16 is slower to first audio and to stop, with no fps benefit.
* **MuseTalk inside LiveTalking is rejected on this GPU** (2.5 fps, 7.9 GB, 6 s to first audio). MuseTalk quality stays in the fifth mode (avatar_engine, lower-face VAE decode, 25 fps at 3.8 GB).
* **Both services can be resident together**: 5.2 GB of 8 GB with both loaded and LiveTalking speaking. They should not speak at the same time (not tested).
* **Launcher VRAM gate (Agent D):** LiveTalking needs about 1.3 GB steady, 1.5 GB with margin for a second session. Start it only if free VRAM >= 2.0 GB (2048 MiB) at launch; with the engine already resident (about 4.8 GB used on the card) free is about 3.4 GB, so it passes. Skip with a message below 2.0 GB. Sequential start: engine first (needs about 4.8 GB free), then LiveTalking. `max_session` 2 is fine for 1.3 GB (second session not benchmarked).
* Cold start of the service to ready: about 25-40 s (model load + warm-up).
