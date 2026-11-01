# ARIA Live validation — 31 October 2026

The current local application is available at `http://localhost:5173`. The earlier experimental legal acknowledgement and policy pages were removed at the project owner's request. The original research ratings, suitability details, portfolio/SIP calculations and saved-report output are available again.

## Actual end-to-end run

`node scripts/live_meeting_dry_run.mjs` created a separate QA account through normal registration and used the actual local application, configured language model, live WebSocket and speech services. No response mocks were used. All five questions received accepted and completed responses with audio; full playback of the first answer completed, captions appeared, subsequent turns were interrupted after checks, history was saved to the same session, and ending the meeting returned to normal chat. There were no browser errors.

The final questions covered an introduction, Nifty versus Sensex, Indian market factors, bond duration and company fundamentals. The last asked for a company name or ticker. The market answer identified its 2026-10-30 index data as delayed and did not assert a current price or a proven cause for the movements. The Nifty/Sensex response was correct in its basic distinctions but lengthy in spoken form; response length remains variable.

Health, authentication, history, profile, progress, research list, market overview/news and instrument search returned HTTP 200. A generated speech sample was successfully transcribed by the configured Whisper endpoint (`Hi!` → `Hi.`). The actual browser speech-recognition service and a human microphone were not tested; the separate browser microphone tests used a synthetic audio device and mocked transcription.

The photo avatar was active in this run. The optional local MuseTalk health request failed because its service was not running. A separate earlier GPU test on the installed RTX 4060 produced 26 distinct frames for 1.788 seconds of audio in 3.886 seconds, slower than realtime. The hands in the seated image are visible but do not gesture. See [avatar validation](ARIA_AVATAR_HANDS_VALIDATION.md) for asset provenance and renderer evidence.

## Microphone repair

Live mode previously relied on the browser's online speech-recognition service, which could leave a spoken question without a transcript. It now records microphone audio and sends it to ARIA's existing Whisper endpoint; a quiet pause submits the question, and the Send speech control can finish it manually. Muting discards the current recording. The browser speech API remains a fallback when recording is unavailable.

An additional actual end-to-end test played synthetic speech through Chromium's fake microphone. The real browser recorder submitted it to the configured Whisper service (HTTP 200), the resulting question entered the real live WebSocket, and the model returned audio and captions. Whisper heard “ARIA” as “area,” but understood the question. Evidence: [microphone run](../.audit/live-microphone/result.json) and [spoken response](../.audit/live-microphone/voice-reply.png). This is not a test of a person's physical microphone, room acoustics or browser permission settings.

## Automated checks

- Frontend production build: passed.
- Accounts, live-avatar backend and market snapshot tests: 34 passed.
- Restored finance, research and accuracy regression suite: 78 passed.
- Focused market/company accuracy suite: 37 passed.
- Meeting, research, settings, markets and navigation browser checks: 16 passed.
- Browser microphone capture/release checks with a synthetic device: 4 passed.

The deterministic regression suites use isolated databases and provider fixtures; the real-provider run above is separate. Financial information and model outputs can still be incorrect or delayed. In particular, a source date does not independently establish source accuracy.

## Evidence

- [Final meeting and office](../.audit/live3/01-office-ready.png)
- [Speaking with captions and chat](../.audit/live3/02-speaking-captions-chat.png)
- [Mobile meeting](../.audit/live3/04-mobile-office.png)
- [Real conversation record](../.audit/live3/real-dry-run.json)
- [Accuracy validation](ARIA_ACCURACY_VALIDATION.md)
- [Avatar validation and generated asset provenance](ARIA_AVATAR_HANDS_VALIDATION.md)
