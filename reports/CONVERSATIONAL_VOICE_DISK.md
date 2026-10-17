# Conversational voice disk

Conversational Mode uses a shared ARIA disk instead of the TalkingHead doll in the root, v1 and v2 interfaces. The latest reply is played through a native audio element with pause, seek, replay and volume controls. No 3D model is loaded for this mode.

The audible element feeds a Web Audio analyser with a 2,048-sample FFT. Time-domain RMS controls the disk's expansion and glow; 64 logarithmically spaced frequency bars show approximately 80–8,000 Hz. The spectral centroid gently changes the disk's angle, and a time-domain waveform shapes the outer ring. These are measurements of the audio signal, not inferred emotions or a pitch transcription. Silence and paused/ended playback return to a calm baseline; rendering does not invent speech movement from a pending network request.

The audio graph is connected before playback, and its context resumes when audio plays. Connecting the graph during a play event could interrupt Chromium playback; the browser tests exposed this timing issue. Native controls allow a manual start when autoplay is blocked. Missing audio leaves text replies usable. Reduced-motion preferences suppress disk expansion/rotation while retaining the measured spectrum. Unmounting disconnects audio nodes, closes the context and cancels animation/resize observers. Clearing chat retains the audio element so a future reply can safely use the same media source.

Implementation: `web/src/components/chat/VoiceDisk.tsx` and `VoiceDisk.css`. The three `ConversationalAvatar.tsx` entry points export this shared component. Live Avatar and Tavus remain separate modes.

Regression coverage uses synthetic WAV audio decoded by Chromium, with quiet 220 Hz and louder 880 Hz segments. It checks measured amplitude and frequency changes, pause, replay, reduced motion, playback completion, clearing and mode exit in both UI versions. Final project-wide outcomes are recorded in `SYSTEM_AUDIT_RESULTS.json`.

After connecting the graph before playback, all six repeated voice checks passed. Eight additional light/dark desktop/mobile previews passed with a real measured synthetic audio signal and no page errors. Screenshots and audio-event diagnostics are preserved locally under the ignored `.audit/voice-disk-preview/` directory. The earlier full browser attempt that exposed the timing failure is retained there and summarized in the portable audit results.

The final full rerun passed 1,158 Python tests, 30 private-mode browser workflows and four account browser workflows. Build, lint (73 existing warnings), both restart checks, memory evaluation, dependency consistency/advisory scans and live intent checks passed. FRED's connection probe timed out; the other six provider probes passed. The overall runner returned exit code 1 because of that external connection failure. No environment configuration, database migration or additional model service was needed for this feature.
