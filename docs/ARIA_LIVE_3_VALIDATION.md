# ARIA Live 3 validation — 2026-10-31

Local application: http://localhost:5173. Implementation and verification performed against the existing ARIA architecture and account system. No deployment performed; `.env` was not modified. Real QA conversations use separate accounts created through normal registration, preserving existing user data.

## A. Findings and repairs

- Short utterances could remain as interim browser recognition results. Finishing speech previously aborted capture and lost them. Send speech now commits the collected utterance; a 1.8-second quiet pause also commits it. Explicit microphone mute discards it. Late recognition events are guarded against duplicate submissions.
- The running API had an older source revision. The existing launcher verified process ownership and restarted only ARIA's backend. WebSocket acceptance now acknowledges receipt independently of LLM generation. Disconnect and response-timeout states clear misleading processing indicators; TTS failures surface turn-specific errors.
- The meeting used a generic sparkle mark. Header, sidebar, empty state and iframe start screen now use the repository's official blue/teal ARIA A assets and shared brand components.
- Opaque canvas and empty sides hid the office. A locally served office image, feathered photo edges and subtle daylight/reflection/monitor animation fill the stage. Reduced-motion preferences disable animation.
- The actual market response exposed older daily prices as today's data and generic keyword news matches. Broad Indian-market news is now filtered to relevant market headlines. Snapshot dates are included in model context, written replies and a deterministic spoken prefix, so summarization cannot remove them.

## B. Connectivity

| Integration | Status | Verification method | Notes |
|---|---|---|---|
| Frontend API | VERIFIED | Real browser on port 5173, authenticated requests | No response mocks in real dry run |
| Backend | VERIFIED | Health revision, account session, real turns | Current source launched on port 8000 |
| LLM provider | VERIFIED | Direct Groq and Gemini calls returned requested text | Configured `openai/gpt-oss-120b` and `gemini-3.6-flash`; provider availability/credits remain external |
| RAG/retrieval | PARTIALLY VERIFIED | Actual SentenceBERT/FAISS returned scored hits | Bond-duration query had low relevance in the small existing concept corpus; no claim of comprehensive coverage |
| Database | VERIFIED | Five real turns read back from same authenticated session | Test accounts/history retained as evidence |
| STT | PARTIALLY VERIFIED | Actual generated audio submitted to configured Whisper | Successful transcription; browser recognition with a human microphone NOT VERIFIED |
| TTS | VERIFIED | Actual server audio chunks decoded and played in Chromium | Local Piper installed; complete first-answer playback observed |
| Avatar | PARTIALLY VERIFIED | Existing photo model/assets rendered with audio | MuseTalk port 8010 refused connection; photo fallback worked. GPU lip-sync NOT VERIFIED |
| WebSocket | VERIFIED | Accepted, text, audio, done frames on five real turns | Same owner/session; interruption and cleanup also regression-tested |
| Market data | PARTIALLY VERIFIED | Real market endpoints and source snapshots | Provider supplied October 29 daily values; current prices cannot be certified. Date disclosure added |

## C. Branding and interaction

Official assets: existing `BrandLogo`/`BrandMark`, `/brand/aria-mark-128.png` and 64px favicon. Main files: `web/src/components/chat/LiveMeeting.tsx`, its CSS, all three ChatTab entry points, `interface/avatar/live.html`, and `api/routes/live.py`.

The meeting remains full viewport with a single avatar iframe. Chat opens without restarting it; text and speech share conversation history. Captions follow actual scheduled audio chunks and clear on interruption. Controls distinguish mute from finishing speech. Session exit restores normal chat. The office contains windows, city view, bookcase, plants, desk and monitor surfaces; monitor graphics are decorative, not live quotes. Motion is ambient CSS animation, not a video of real people.

## D. Executed tests

| Test | Result | Evidence |
|---|---|---|
| Frontend startup/build | VERIFIED | Vite startup; `npm run build` passed |
| Backend startup | VERIFIED | Launcher health/revision and authenticated session checks |
| API connectivity | VERIFIED | Health, office asset, auth, history, profile, progress, research list, market overview/news and instrument search |
| Text conversation and streaming | VERIFIED | Five real WebSocket questions with text/audio/done |
| Voice input | PARTIALLY VERIFIED | Whisper audio loopback; deterministic recognition-control tests |
| Voice output | VERIFIED | Real audio playback plus Whisper transcription of generated sample |
| Avatar response | PARTIALLY VERIFIED | Photo renderer confirmed; MuseTalk unavailable |
| Captions/chat synchronization | VERIFIED | Actual speaking screenshot and same-session history; controlled timing/interruption regressions |
| Responsive UI | VERIFIED | Desktop/mobile screenshots inspected; six viewport regression checks |
| Live backend regressions | PASSED | 12 tests in `tests/test_live_avatar.py` |
| QA and market regressions | PASSED | 72 tests across `tests/qa`, API markets and initial snapshot tests; all 3 snapshot tests rerun after adding spoken-date coverage |
| Meeting regressions | PASSED | 8 passed; optional renderer smoke skipped in this suite because separate real dry run loads actual assets |
| Cross-app regressions | PASSED | 12 passed across both UI versions: Explore search, saved research, company intelligence, profile/progress, settings/markets, chat/export and all navigation destinations |

Regression fixtures isolate provider boundaries and are not counted as proof of working real integrations. Real evidence comes from `scripts/live_meeting_dry_run.mjs` and `.audit/live3/provider-probes.json`. The former can be rerun against the running local app and creates a fresh QA account each time.

## E. Limits and next actions

- Human microphone capture and the browser vendor's speech-recognition service need a manual Chrome/Edge test with microphone permission. A successful Whisper endpoint test does not prove that browser service works. A listening screenshot is therefore not presented as verified evidence.
- MuseTalk is not running at localhost:8010. Use the existing GPU launcher only on suitable installed hardware to validate that renderer. The photo avatar uses audio-driven mouth deformation, not photorealistic neural lip-sync.
- Hosted speech/browser services, Groq, Gemini and external data feeds depend on network availability, credentials and credits. Both configured LLM credentials worked during this run; no credentials are included here.
- Daily market snapshots are delayed and may precede the current session. News/LLM synthesis is not proof of causal market drivers or financial accuracy. Check the dates now stated in replies.
- The final market summary still used "today" after its mandatory date notice and included a questionable oil-price currency interpretation. Date disclosure is fixed, but semantic financial accuracy is only PARTIALLY VERIFIED; the full response is retained in the evidence. The existing INR-only market prompt can misstate internationally quoted commodity units and needs a separate grounding improvement.
- Captions are chunk/sentence synchronized; authoritative word timestamps are not supplied by the backend. Half-duplex capture pauses while ARIA speaks. Already-running synchronous calculations may finish and persist after presentation interruption.
- Existing FastAPI/Starlette deprecation warnings remain. Changes are local; no production hosting deployment was requested.

## F. Screenshots and raw evidence

- [Initial meeting and complete office](../.audit/live3/01-office-ready.png)
- [Speaking, captions and open chat](../.audit/live3/02-speaking-captions-chat.png)
- [Conversation transcript](../.audit/live3/03-transcript.png)
- [Mobile office](../.audit/live3/04-mobile-office.png)
- [Mobile chat](../.audit/live3/05-mobile-chat.png)
- [Real dry-run record](../.audit/live3/real-dry-run.json)
- [Provider probes](../.audit/live3/provider-probes.json)

## Office asset provenance

Generated with the built-in image-generation tool using the existing portrait as an environmental reference; the original avatar identity asset is preserved. Generated source: `C:/Users/jtmah/.codex/generated_images/01a18d19-d352-71d1-98cb-9d004c71fb7e/exec-1f50bb72-8426-4b6b-bbf5-20ac9fe4340a.png`. Optimized local asset: `interface/avatar/office.webp` (90,442 bytes).

Prompt specification: wide 16:9 photorealistic empty financial research office matching the portrait's cool daylight and silver-gray glass; left city windows, bookshelf and plants; right walnut workstation, abstract unlabeled monitors, glass and greenery; calm center for the original avatar; no people, logos, numbers, UI or neon. Ambient motion is implemented in CSS on top of this raster asset.

## Final actual five-question run

All five turns received accepted and done events with audio. The first answer played to completion; subsequent answers were interrupted after their response and caption checks. Timing below is browser send-to-complete-audio-generation time, not time to first sound. Performance varied substantially between runs.

| Question | Complete response time | Audio chunks | Outcome |
|---|---:|---:|---|
| Hello ARIA, introduce yourself and explain what you can help me with. | 12.54s | 9 | Answered introduction |
| Explain the difference between Nifty 50 and Sensex. | 14.21s | 9 | Explained indices; snapshot notice spoken |
| What factors influence today's Indian stock market? | 67.28s | 8 | Answered with dated snapshot notice; semantic caveats above |
| Explain what a bond's duration means. | 49.73s | 9 | Explained duration |
| Can you analyse a company's financial fundamentals? | 36.04s | 8 | Returned company lookup failure instead of asking which company; answer-quality issue remains |

Final run: complete=True; browser errors=0; same session=True; session exit=True. Whisper returned HTTP 200 and transcribed the generated sample correctly. Only failed browser network request: optional MuseTalk health endpoint on port 8010. All recorded HTTP endpoint checks returned 200.

The earlier real run correctly asked which company for the fifth question; the repeat instead returned a lookup failure. This is a nondeterministic intent/entity-resolution limitation, not a disconnected service. Company-specific analysis should use an exact listed name/ticker. It is not counted as a successful fundamentals analysis.
