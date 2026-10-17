# Conversational microphone toggle

In Conversational Mode, click **Speak** once to start listening. The same control becomes **Stop listening**. Click it again to stop the microphone, transcribe the recording, send the recognized question and play the latest reply through the ARIA disk. There is no separate Send step for this voice flow, and the microphone does not restart after the answer. Typed questions still use the existing Send control.

Starting a new recording pauses ARIA's current reply to avoid recording its speech. That user click also resumes the disk's audio context so a later answer can play automatically when browser policy permits it. Native reply controls remain available if playback is blocked.

All UI versions use one shared recorder. Its state machine distinguishes microphone permission, recording and transcription/answer processing. The disk shows opening, listening and preparing-reply states. Synchronous state guards prevent duplicate starts/stops, and processing disables the microphone control until the answer returns. Typed submission is disabled while recording/processing to avoid competing sends. Capture chooses a supported recorder format and sends a matching filename extension. Normal Mode continues to place the transcript in its input for manual submission.

Permission denial, recording failure, empty audio/transcripts and transcription failures show an error without submitting a question. Mode/session changes, chat clearing and unmounting release microphone tracks and abort pending transcription. If permission arrives after the user cancels, the late stream is immediately released. Recordings respect the existing 10 MB upload boundary.

Browser coverage uses full Chromium with a synthetic microphone device, real getUserMedia/MediaRecorder capture and multipart upload, a controlled transcription response and synthetic answer audio. It verifies both clicks, exactly one automatic chat submission, automatic reply playback and measured disk activity, busy-click protection, interruption of a speaking reply, denial/empty-transcript behavior, clear/mode-exit cleanup, late permission cancellation and Normal Mode's manual-send behavior. The lightweight Windows headless shell returned NotSupportedError for capture; these tests select full Chromium explicitly. This verifies browser integration, not physical microphone quality or a live speech-provider transcription.

Current regression outcomes are recorded in `SYSTEM_AUDIT_RESULTS.json`.

Final rerun: 1,158 Python tests, 34 private-mode browser workflows and four account browser workflows passed. Build, lint (74 warnings), both restart checks, memory evaluation, dependency checks/advisory scans and live intent checks passed. FRED's connection probe timed out; the other six provider probes passed, so the overall runner returned exit code 1 for the connection check. The four new microphone workflows passed in the full run in addition to eight repeated focused checks.
