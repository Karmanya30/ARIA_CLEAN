# Measurements (22 Oct 2026, branch audit/system-review-20261016, HEAD 5c04552)

## STATUS (finished 25 Oct 2026): all six items measured (the LiveTalking and Local Avatar modes were later removed, so their numbers are historical)

Done: 1 lip-sync lag, 2 browser comparison of the 5th (in-house engine) and 6th (LiveTalking) chat modes, 3 both avatar services at once + second sessions, 5 launcher port-8000 scan (isolated logic test).
Still to measure: 4 flaky forecast test (10 runs idle, 10 loaded, robust fix if it is a timing assumption), 6 end-to-end question latency for all six chat modes.
After that: refresh the recommendation validation (scenario_report_validation.py --all, then --robustness --rebuild-cache, then make_summary_pdf.py), run the full test suite and the web build, check both launchers, secrets scan, commit and push (no Claude attribution).
Main findings so far: LiveTalking interrupt in the browser keeps audio audible about 1.3 s (WebRTC playout buffer) although the server flush is 0.32 s; running both avatars at once saturates the GPU (LiveTalking falls to about 6.5 fps), so use one avatar mode at a time.


PARTIAL: updated after each item. "not yet measured" marks what is still to do.

Machine: RTX 4060 Laptop 8 GB, 16 GB RAM (free RAM 0.4-1.9 GB during these runs: other projects, AWCC, audiodg are active, so the machine was NOT quiet).
Services: engine on 8010 (started by the launcher), LiveTalking on 8020 (started by `scripts\start_livetalking.bat`), ARIA API 8000 runs in `accounts` mode (chat needs sign-in), so measurements that need chat use a second API (`ARIA_AUTH_MODE=private`, temp DB) on 8002 and a second Vite on 5190 (`ARIA_API_PORT=8002`). No microphone or speech recognition was used (headless Edge, SpeechRecognition undefined, getUserMedia rejected).
Idle VRAM with both services resident: 5.1 GB.
Note: the first engine start was slow (about 14 min) because a duplicate engine was loading at the same time with ~0.4 GB free RAM. After that the engine ran at 25 fps (earlier trial runs at 17-20 fps and 2-6 s first frame were taken during that thrash and are discarded).

## 1. Lip-sync lag

Method. Engine: real WebSocket, text with plosive-initial sentences (onset test) and the 16 s paragraph, 5 runs each. Audio RMS envelope (10 ms) and mouth-ROI motion energy (mean abs difference of consecutive frames inside the lip box 200,210-300,265 of the 512 px output) both binned to 25 Hz; cross-correlation in +-12 frames with parabolic sub-frame interpolation; positive lag = mouth later than audio. Time base = the stream timestamps in the 9-byte frame headers (what the server emits).
LiveTalking: test wav (Piper words with 0.8 s digital silence between them, 8 onsets) fed through `/humanaudio`; measured in headless Edge's own WebRTC playout (MediaStreamSource -> ScriptProcessor RMS stamped with performance.now; `requestVideoFrameCallback` expectedDisplayTime + mouth-ROI pixels), 5 runs of the 15.8 s clip on one peer connection. Same motion-energy / 25 Hz xcorr.
Estimator self-test: shifting the engine audio timestamps by 40/80/120/200 ms moved the estimated lag by 40/81/119/198 ms (error <= 3 ms), so the estimator itself is sound; the uncertainty is in the signal.

| Avatar | xcorr lag, linear envelope (median / p90) | xcorr lag, log envelope (median / p90) | corr | first mouth motion minus first audio (median / p90) |
|---|---|---|---|---|
| Engine, onset sentences, stream clock | -66 / -35 ms | see raw | 0.24 | -62 / -20 ms |
| Engine, 16 s paragraph, stream clock | -18 / -8 ms | -10 / -10 ms | 0.22 | -67 / -57 ms |
| LiveTalking, Edge playout | -112 / -8 ms | -128 / -52 ms | 0.45 / 0.58 | -377 / -315 ms |

Reading: negative = mouth moves BEFORE the audio. Engine: mouth leads by roughly 10-70 ms, i.e. within 1-2 frames, never late. LiveTalking: mouth leads by about 110-130 ms by cross-correlation (drift over the clip thirds: -50, -155, -100 ms, so no monotonic drift); the generated-mouth patch starts about 0.35 s before the first audible sound (Wav2Lip lead-in), which does not by itself mean the mouth opens that early.
Limits: 25 fps quantisation (40 ms) and +-1 frame in all values; correlation only 0.2-0.6 (head sway in the engine ROI, H.264 noise and small Wav2Lip mouth motion), so treat +-60 ms as the real uncertainty; the ScriptProcessor taps audio before the output device (about 20-40 ms) so audible lag is that much more positive; the engine value is server stream time, not browser playout (browser playout offset is in item 2: video drawn minus audio audible, median about +7..13 ms); the burst-onset estimate was too noisy to use (per-burst values -240..+440 ms). Raw: scratchpad `m\raw_*`, `ls_engine.json`, `raw_ltb.json`.

## 2. Engine (5th) vs LiveTalking (6th) mode in headless Edge

Method. Headless Edge via CDP (SpeechRecognition undefined, getUserMedia rejected, no microphone), page served by the second Vite (5190, proxy to the private API on 8002). The chat reply is mocked in the page (canned finance answer after 600 ms) so only the avatar path is timed; "reply" = the moment the reply reached the page. Question typed through the composer, 1 warm-up run discarded then 5 measured runs per mode, then 5 interrupts (typing in the composer = barge-in). Engine: instrumentation hooks in `avatarClient.ts` (`__avTrace`, scheduled audio start corrected by `getOutputTimestamp`, frames drawn by the rAF painter). LiveTalking: `RTCPeerConnection.getStats()` at 40 Hz (audioLevel > 0.005 = audible) and `requestVideoFrameCallback`. Script: scratchpad `mr_modes.mjs`, raw `br_engine.json`, `br_lt.json`.
The speech text is cached by the API after the first request (spoken fetch 30 ms), so the numbers below exclude TTS synthesis time; the uncached first request of the same text took 8-9 s in the earlier trials (that cost is part of item 6).

| Metric (median / p90, n=5) | Engine (5th mode) | LiveTalking (6th mode) |
|---|---|---|
| reply to first audio (audible, output-latency corrected) | 1564 / 1627 ms | 2151 / 3465 ms |
| reply to first drawn speech frame | 1555 / 1617 ms | not separable (see below); "speaking" state at 1727 / 3397 ms |
| fps while speaking (drawn) | 25.0 / 25.0 | 24.8 / 25.1 (min 24.0) |
| dropped / late frames per answer | 0 / 2 (received 25.0 fps, drawn 25.0) | 0 / 31 (browser `framesDropped`) |
| audio underruns | server 0 in all runs; 0 chunks scheduled late | not exposed; `concealedSamples` 30360 / 71040 per answer (0.7 / 1.6 s of concealment), `freezeCount` 2 / 4 |
| longest gap between drawn frames | 79 / 79 ms | no freeze > 200 ms in any run |
| a/v drift (video drawn minus audio audible) | -7 / -7 ms | not measured (separate WebRTC tracks) |
| interrupt: audio actually stopped | 25 / 36 ms after the event (+40 ms output device latency), 0 chunks scheduled afterwards | stop request sent after 25 / 32 ms, but audio stayed audible for 1297 / 2319 ms (min 968 ms) |
| interrupt: state back to idle | 28 / 41 ms | 28 / 34 ms |
| console errors | 1 per page (below) | 1 per page (below) |

Reading. The engine mode starts about 1.6 s after the reply and plays smooth 25 fps. LiveTalking starts 1.8-3.5 s after the reply, also at about 25 fps, but its WebRTC playout buffers 0.4-0.8 s of audio (jitter buffer delay 426 / 835 ms) and the interrupt only silences it after 1-2.3 s because the already-buffered audio keeps playing: this is the one real weakness found (barge-in feels late on LiveTalking). The reply-to-first-mouth-motion figure for LiveTalking is not usable (idle head motion trips the detector: 0.4 to 16 s), so no first-drawn-frame number is claimed for it.
Console errors: every page logs one `Error: Conversation belongs to another owner` (uncaught, from `api.ts` when the page reloads a conversation created under another owner id in my harness); it appears in both modes and in the fallback test, and is a test-harness artefact, not a speech failure. No other console errors.
Earlier trials in this file's history that showed "1 fps" were a counting bug in the script (frames were matched by stream timestamp); fixed (frames now counted by wall-clock window), and a 3 s probe showed requestAnimationFrame running far above 25 Hz, so the page really draws 25 fps.

Fallback when the service is unreachable. A third Vite (port 5191, then stopped) with `ARIA_AVATAR_PORT=8999` and `ARIA_LIVETALKING_PORT=8998` (dead ports; the real services were untouched):
- Engine mode: notice "The live face is not available (The local avatar engine is not running), so ARIA's disk is shown. We will switch back once it is running." after 0.28 s, voice disk shown, the reply still arrived and was displayed.
- LiveTalking mode: notice "LiveTalking service is not running: start the Lip-sync GPU launcher. ARIA's disk is shown meanwhile, ..." after 0.74 s, disk shown, reply displayed.
The automatic switch back when the service returns was not tested.
Limits: n=5, headless Edge with software rendering, machine not quiet; p90 of 5 is essentially the second worst run.
## 3. Both services speaking at once, second session behaviour

Both avatars at once. Two headless Edge sessions (one per mode, `br_modes.mjs engine 5` and `lt 5` started 25 s apart so the speaking phases overlap for most of the run), nvidia-smi at 1 Hz (386 samples, `vram_both.csv`).
- VRAM: idle 5104 MiB (both models resident); peak 5145 MiB (+41 MiB) of 8188 MiB; GPU utilisation up to 100 percent (mean 23 percent over the whole window). No OOM, no engine "GPU out of memory" state, server underruns 0.
- Engine while LiveTalking also speaks (n=5): reply to first audio 2115 / 4162 ms (median / p90, vs 1564 / 1627 alone), drawn fps 23.7 / 25.0 (min 22), dropped frames 26 / 41, longest draw gap 690 / 1349 ms, 1 starved audio chunk in the worst run, server ttfb 1719 / 3797 ms.
- LiveTalking while the engine also speaks (n=5): reply to first audio 3374 / 4181 ms (alone 2151 / 3465), fps while speaking 6.5 / 6.7 (min 3.7) instead of 24.8, freezes over 200 ms 46 / 164 per answer, browser freezeCount 24 / 46, concealed audio 2.0 / 2.5 million samples (about 40-50 s of concealment counted over a 14 s answer, i.e. the audio stream is badly broken), audio jitter buffer 649 / 760 ms. So with both on one 8 GB GPU and this CPU, LiveTalking becomes unusable (about 6 fps) while the engine stays roughly fine. Caveat: the two headless Edge decoders and the loaded CPU contribute, so this is the whole-machine effect, not GPU alone.
- Interrupt (LiveTalking, both active): audible for another 1204 / 2532 ms after the stop request (alone 1297 / 2319). Engine: stops within the same 25-40 ms.

LiveTalking second session (max_session 2; `sess_lt.mjs`, real /offer calls from headless Edge via the proxy, no microphone). Busy answer: HTTP 200 with JSON `{"code":-1,"msg":"Maximum session limit reached (2/2)"}` in about 150 ms (the page maps this to its busy state). Slots: this run started with ONE slot already occupied by a leftover/stale session (health said sessions 1 before the test), so only one offer was accepted (1.27 s) and the second was refused.
- Graceful close (client `pc.close()`): the slot was free after 2.2 s and a new offer succeeded (0.59 s).
- Browser killed without closing (headless Edge `kill`): the two sessions started at 2; one slot freed after about 40-48 s; one session was still counted 300 s later (poll stopped there). That one is the stale session that was already present before the test, so a session whose browser died ungracefully can hold a slot for at least 5 minutes (possibly indefinitely, until the LiveTalking process restarts). I did not restart LiveTalking. Net: with a closed tab the slot frees in a few seconds; with a crashed browser it frees in about 45 s for some sessions and apparently never for others.
Engine second session (1 session; raw WebSocket to /stream, `sess_eng.mjs`). A second connection without `takeover=1` gets `{"type":"state","value":"unavailable","reason":"busy: another live session is active (reconnect with takeover=1 to replace it)"}` and close code 1013 within 12 ms; the first session is not disturbed. After the first session closed, a new one was accepted after 375 ms (first retry). With `takeover=1` the new session gets "idle" and the old one receives "unavailable: replaced by a newer session" (the web app then shows the "Use it here" notice).
Correction on the stale LiveTalking slot above: the health count went 1, then 2 again between my tests with no test of mine running, so the "stuck" slot may belong to another browser tab that is genuinely connected (for example someone using the 6th mode), not necessarily a leaked session. I cannot tell the two apart from `/health`, so treat "never freed" as unproven; the two certain facts are: closed tab frees its slot in about 2 s, killed browsers free theirs in about 45 s (the sessions I created).

## 4. Flaky test: not yet measured
## 5. Launcher port-8000 case

Verified by running the REAL scan lines of `scripts\aria_launcher.ps1` (lines 36-39 functions and 90-95 scan, extracted and shifted to ports 18000-18019 with stub listeners; ARIA's own 8000 untouched):
- nothing listening: picks the first port, no warning;
- non-ARIA http app on the first port: picks the next, logs "Port 8000 is used by another app; ARIA API goes on port N";
- non-ARIA on first and an ARIA API (openapi title "ARIA API") on the next: reuses that one, starts nothing;
- two non-ARIA ports: picks the third;
- raw TCP listener (not http): Test-AriaApi fails safely, port skipped;
- all 20 ports busy: throws "No free port between 8000 and 8019 for the ARIA API".
Also: a second Vite started with `ARIA_API_PORT=8002` proxied `/api` to the API on 8002 (session endpoint answered `private` from 8002 while 8000 says `accounts`), so the port hand-over to the web app works.
Not verified: the real launcher end to end with something holding 8000 (would need stopping ARIA's API), the "API already starting" branch (reads real processes), and the later "Test-CurrentApi"/restart branches on a non-8000 port.

## 6. End-to-end question latency: not yet measured
## 4. Flaky forecast test (measured 25 Oct 2026)

tests/forecast/test_universe.py::test_timeout_isolated_and_sweep_never_raises: 10 runs idle all passed (21.1-22.3 s). 10 runs with all 22 cores busy: all passed, 23.1-44.8 s. The only timing assumption is `time.time() - t0 < 90` (the worker timeout is 20 s plus process spawn); the one earlier failure happened with the full suite and other projects running at once, so 90 s had too little headroom. Fix: bound raised to 180 s (still proves a hung worker cannot stall the sweep). Not reproduced after that.

## 6. End-to-end question latency, five chat modes (measured 25 Oct 2026)

Method: second API on 8002 (ARIA_AUTH_MODE=private, temp DB on E:), POST /api/chat, 3 questions x 3 runs per mode (45 calls, all returned 200). Text answer only (the avatar speech/video stage is measured in sections 1-3). The model/network was not quiet and C: was full, so treat as indicative.

| Mode | median | p90 / max |
|---|---|---|
| Normal | 5.7 s | 60.5 s |
| Conversational | 7.2 s | 51.0 s |
| Live Avatar (Free) | 13.2 s | 43.2 s |
| Tavus CVI | 17.3 s | 36.9 s |
| Local Avatar | 19.4 s | 30.9 s |

By question: PE ratio of Reliance 9.2 s, capital of France 17.3 s, invest in HDFC Bank 30.6 s (median of 15 each).
Reading: the mode only changes presentation, so the ordering across modes is NOT a real per-mode cost. It follows run order and model/network variance (a simple factual question was slower than the PE lookup, which points to the model call, not the pipeline). The tail (30-60 s) is the language-model call; no mode is systematically slower. A proper comparison needs interleaved runs and a fixed model; not done.
