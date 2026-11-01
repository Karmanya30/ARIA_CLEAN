# ARIA Live meeting implementation

Open Chat in either UI version, select **Live Avatar (Free)**, then select **Start conversation**. The meeting starts with the microphone muted. Speak enables the existing continuous browser recognition; Interrupt stops ARIA's queued response. Opening chat keeps the same iframe, renderer, audio context and WebSocket alive.

## Architecture assessment

- React 19, TypeScript and Vite; `VersionRouter` lazy-loads v1 or v2. Each version uses hash navigation and its own `ChatTab`. The root component copy is also maintained.
- The live renderer is `interface/avatar/live.html`, served by FastAPI at `/avatar/live`. Its existing fallback order is local MuseTalk, the MediaPipe animated photo with glasses overlay, then TalkingHead/HeadAudio with the existing GLB asset.
- Voice follows browser SpeechRecognition → `/api/live/ws` → `modules/qa/pipeline.answer` → existing financial routing, owner/profile context and conversation memory → sentence TTS through `ai.speech.live_tts` → Web Audio playback and the existing avatar lip-sync renderer.
- The live socket sends text, audio chunks, thinking and done messages with a client-provided turn number. Text and voice now both enter that socket from the same meeting. The existing `/api/chat/history` endpoint supplies the durable, full written answers.
- Authentication remains in the existing AuthGate/API middleware. The meeting explicitly supplies the account-aware `ownerId()` to the iframe. Both directions of the message bridge verify the sender window and same origin.
- `core.session.execute_turn` already serializes conversation writes. Interrupting presentation does not delete a completed answer or create a second conversation store.

## Changes

| File | Responsibility |
| --- | --- |
| `web/src/components/chat/LiveMeeting.tsx` | New shared full-viewport meeting portal, session state bridge, elapsed timer, controls, sliding transcript, text composer, exit confirmation and focus management. |
| `web/src/components/chat/LiveMeeting.css` | Charcoal/green meeting layout; desktop stage resize, mobile chat overlay, reduced-motion handling, focus outlines and transcript styling. |
| `web/src/components/chat/ChatTab.tsx` and `web/src/versions/{v1,v2}/components/chat/ChatTab.tsx` | Enter the shared meeting; refresh the original conversation on return; remove the old embedded live split layout/poller. |
| `interface/avatar/live.html` | Preserve all three renderers; add same-origin controls/state events, actual playback caption scheduling, microphone and connection states, interruption guards and resource cleanup. |
| `api/routes/live.py` | Report TTS failures as recoverable, turn-scoped WebSocket errors and clean up the speaker task. |
| `web/src/components/chat/Markdown.tsx` | Reuse the existing Markdown component with GFM tables. |
| `web/package.json`, `web/package-lock.json` | Add `remark-gfm` for table/structured Markdown support. |
| `web/e2e/live-meeting.spec.ts` | Meeting integration, playback, responsive and optional real-renderer browser tests. |
| `tests/test_live_avatar.py` | TTS failure recovery and preservation of the written answer. |

No new hooks, backend endpoints or avatar assets were required. The conversational recorder retains its existing implementation.

## Interaction and lifecycle

- Microphone mute aborts recognition without stopping speaker audio. Recognition callbacks from an aborted or outdated recognizer are ignored. Permission denial, missing audio capture and unsupported speech recognition have explicit messages; text chat remains available.
- Text messages interrupt an active response and go through the same live socket and session as voice. Client turn guards reject old audio, including after asynchronous decoding.
- Chat remains mounted but inert while closed. Opening it focuses the composer; Escape/Close restores the Chat button's focus. Dashboard controls become inert during the meeting. The exit confirmation traps keyboard focus.
- The textarea supports Enter to send and Shift+Enter for new lines. Markdown tables, lists and emphasis render through the existing Markdown component.
- The connection indicator follows socket readiness. Reconnects stop old capture and playback, invalidate old turns and preserve the session. Authentication/policy rejection does not trigger an endless reconnect loop.
- Ending the meeting stops recognition, clears watchdog/reconnect timers, stops queued audio, closes the audio context/socket and cancels MuseTalk fetches. Completed answers remain in the existing history. A draft or unfinished answer triggers a confirmation.
- Transcript refreshes are guarded against stale requests and continue during the meeting, including when an interrupted backend calculation finishes saving later. The original chat reloads history when the meeting closes.

## Caption synchronization

Incoming full text updates the transcript, not the subtitle overlay. Each audio chunk supplies its own text:

- **Animated photo:** schedules captions at the same AudioContext start time as its AudioBufferSource.
- **MuseTalk:** schedules captions when buffering completes and the audio source actually starts; audio-only fallback also schedules its matching caption.
- **TalkingHead:** uses the pinned library's timed marker at the beginning of the audio clip, preserving the existing HeadAudio/text-timed lip-sync behavior.

The watchdog reads the actual audio clock. Captions remain at sentence/chunk level because the backend has no authoritative word timestamps. Toggling CC only hides/shows the overlay. Interruption invalidates queued captions and audio together. The full written response remains in conversation history.

## Validation

Results on 2026-10-30: production build passed; all 10 meeting/voice browser tests passed. The initial live-avatar and conversation-memory backend run passed 39 tests; the updated live-avatar suite, including the new TTS failure case, passed all 12 tests. `git diff --check` passed. Real configured-photo screenshots were inspected and retained under `.audit/live-meeting-preview/`.

Validation commands from the repository root:

```powershell
npm --prefix web run build
.venv\Scripts\python.exe -m pytest tests/test_live_avatar.py tests/test_conversation_memory.py -q
cd web
$env:ARIA_REAL_AVATAR_SMOKE='1'
npx playwright test e2e/live-meeting.spec.ts e2e/voice-toggle.spec.ts
```

The deterministic meeting suite uses the actual iframe controller and browser Web Audio decoding, with mocked recognition, socket responses and TalkingHead provider boundary. It covers both UI versions, shared text/voice session IDs, caption order, CC toggling, mute during playback, stale chunks/results, interruption, permission denial, reconnection, draft confirmation, Markdown tables and avatar continuity when opening chat.

Responsive checks cover 1920×1080, 1536×864, 1366×768, 1024×768, 768×1024 and 390×844. The optional real-avatar smoke test loads the configured assets and renderer and captures desktop, chat-open and mobile screenshots with controlled audio. The existing voice-toggle tests cover real Chromium media capture with a fake media device and mocked transcription/chat providers.

For the subsequent connectivity repairs, office/branding update and real-provider dry run, see [ARIA Live 3 validation](ARIA_LIVE_3_VALIDATION.md). Its current results supersede the initial verification limits below.

## Remaining verification limits

- A real human microphone conversation with the production STT, LLM and TTS services was not exercised. The renderer smoke test used the configured animated photo; an available local MuseTalk GPU server and the real TalkingHead fallback still need service-specific live playback checks.
- Speech recognition remains the existing browser API and needs a supporting browser such as Chrome or Edge. Speak starts listening; Send speech commits collected interim words. Explicit mute discards them. The existing half-duplex design pauses capture while ARIA responds; interruption is explicit through the toolbar or a new text question.
- Stopping a response cancels its presentation task, but a synchronous financial pipeline calculation already running in a worker thread may finish and persist afterward. The existing session lock preserves ordering.
- Existing project deprecation warnings remain. Dependency audit reports a pre-existing Vite development-server advisory; the Markdown addition did not introduce that finding.
- This change is implemented in the local repository; it does not deploy or migrate the application to another hosting service.
