# ARIA Product Inventory (Phase A, frontend auditor)

Status: DRAFT v1 written incrementally (static inventory from source). Live-DOM counts are added below as probes finish.

## Baseline and snapshot rules
* Committed baseline: `984ffbb` (main). Auditor started on branch `evaluation/pre-launch-audit`.
* The working tree has ~111 uncommitted modified files from another session (66 under `web/src`). I did NOT touch or revert them. Everything the browser served to me is the working tree.
* Items marked **[WT]** = working tree, uncommitted (absent or different at 984ffbb). Items marked **[BASE]** = verified in `git archive 984ffbb` copy (extracted to scratchpad, grep evidence).
* Labels: VERIFIED / SUSPECTED / RECOMMENDATION / UNTESTED / BLOCKED.

## 1. Application shell (VERIFIED from source)
| Layer | File | Notes |
|---|---|---|
| Entry | `web/src/main.tsx` | `<AuthGate><VersionRouter/></AuthGate>` (no StrictMode comment removed in WT) |
| Auth gate | `web/src/AuthGate.tsx` | `ARIA_AUTH_MODE=private` -> app directly; `accounts` -> sign-in / create-account form (+ optional Google button), Account `<details>` with Sign out / Sign out all devices |
| Version router | `web/src/VersionRouter.tsx`, `version.ts` | `v1` (default, "Stable") / `v2` ("New"). Chosen ONLY by `localStorage.aria_version`; there is no UI to switch (e2e test title: "technical version picker is gone"). Real users always get v1. |
| App | `web/src/versions/vN/App.tsx` (v1 and v2 are byte-identical) | hash router `#/<tab>`, History API with in-app index, Back bar, skip link, disclaimer strip, global search, instrument drawer |

### Dead / duplicated code (VERIFIED by import-graph script from `main.tsx`)
* `web/src/App.tsx` and ~75 files under `web/src/components/**` (root copies of tabs) are NOT reachable from `main.tsx`; only `components/brand/*`, `chat/VoiceDisk`, `chat/LiveMeeting` [WT], `feedback/*` [WT], `chat/NormalModeOrb`/`CompanySearch` style shared bits are imported by versions. `versions/vN/styles/*`, `versions/vN/version.ts`, `versions/vN/index.css` are also unreachable (themes come from root `src/styles/*`). `components/markets/NewsFeed.tsx.bak` is a stray backup file. v1 and v2 differ only in ChatTab, MessageBubble, ThinkingStatus, VoiceRecorder, TemplateCards and Markdown CSS/TSX (diff -rq). Risk: fixes applied to root copies do not ship (see UX-001..).

## 2. Routes / pages (hash routes)
| # | Route | Page | In nav (classic/vitara) | In nav (markets/clear) | Notes |
|---|---|---|---|---|---|
| 1 | `#/chat` | Chat | yes (1st) | yes | default tab except `vitara-markets` (default `markets`). **[WT]** default mode is "Live Avatar (Free)" (full-screen Live Meeting dialog) [BASE: default "Normal Mode"] |
| 2 | `#/markets` | Markets dashboard | no | yes | only themes `vitara-markets`, `vitara-clear`; direct URL in other themes falls back to default tab |
| 3 | `#/explore` | Explore (instrument search + watchlist) | yes | yes | |
| 4 | `#/research` | Research reports (saved reports) | yes | yes ("Reports" short label in Clear) | |
| 5 | `#/intelligence` | Company intelligence + sentiment scorer | yes | yes | |
| 6 | `#/profile` | Your Finance Profile | yes | yes | wizard + transactions + statement upload + insights |
| 7 | `#/progress` | Your Learning Progress | yes | yes | |
| 8 | `#/feedback` | Feedback form | **[WT]** yes | **[WT]** yes | absent at 984ffbb [BASE: no `components/feedback`, no sidebar entry] |
| 9 | `#/settings` | Settings (theme, colour mode, tone, forget style, about) | yes | yes | |
| 10 | `#/disclaimers` | Disclaimers | no (link only: strip, Settings, drawers) | no | `EXTRA_ROUTES`; wording changed in WT ("1 November 2026" vs [BASE] "13 October 2026") |
| — | any unknown hash | falls back to default tab | | | no 404 page |
| — | `/api/*`, `/avatar/live`, `/embed` | proxied backend pages; `/avatar/live` is the iframe used by Live mode | | | |

Auth pages (accounts mode only, not rendered in private mode): Sign in, Create account, Account menu. UNTESTED in this run (needs `ARIA_AUTH_MODE=accounts`; `web/playwright.accounts.config.ts` exists and was not run).

## 3. Themes and colour modes (VERIFIED `theme.ts`)
`classic` (default, left sidebar), `vitara` (top nav), `vitara-markets` (ticker tape + Markets + Light/Night toggle), `vitara-clear` (roomier, Light/Night/Auto, shorter tab labels, "New chat", "Search anything"). Colour mode radios only visible in markets/clear themes. Theme persisted in `localStorage.aria_theme`, mode in `aria_mode`; `?theme=` and `?mode=` URL params are honoured by `index.html` (any string accepted for theme -> unknown values fall back to Classic in JS but the `data-theme` attribute is set raw by index.html).

## 4. Global components
Disclaimer strip (fixed, long/short copy), skip link, Sidebar (brand, global Search button + Ctrl+K dialog, New session/New chat, Mode toggle [markets/clear], tablist nav, tagline), Back bar, Ticker tape (`vitara-markets` only, pause toggle), Instrument drawer (dialog, any instrument), Global search dialog.

## 5. Per-page component and control inventory
(Controls enumerated from source; live DOM counts in section 7.)

### Chat (`ChatTab`, v1/v2 variants)
* Top bar: Mode `<select aria-label=Mode>` — **[WT]** options Normal / Conversational / Live Avatar (Free); **[BASE]** also `Tavus CVI Mode (WebRTC)`; Clear button (`aria-label="Clear chat"`, no confirmation); "Back to chat"/"End and go back" in split layouts.
* Hero state (Normal mode, empty history): orb, brand, greeting, ContextStrip (profile summary / "fill quick form"), Onboarding card (3-step: income, goal, risk; Save/Back/Skip), Composer (VoiceRecorder mic, `Message ARIA` input, Send), TemplateCards x4 (Personal Finance, Tutor, Market Analysis, Equity Research).
* Thread: MessageBubble (user/assistant), ThinkingStatus, ResponseCard, ResearchReport (expandable, tables, debate, downloads), IntelligenceSummary, QuizWidget (radio options + Submit), Markdown renderer, audio playback controls, "Try again", "use original" (spell-correction), "Upload a statement"/"Fill quick form" links, follow-up suggestion chips.
* Conversational mode: VoiceDisk (amplitude disk) + mic toggle + composer.
* Live mode: iframe `/avatar/live` (TalkingHead avatar, WebSocket `/api/live/ws`). **[WT]** wrapped in `LiveMeeting` full-screen `role=dialog aria-modal` with toolbar: mute mic, speak/interrupt, captions toggle, chat toggle (side panel with log + textarea + Send), End, Leave, confirm-leave alertdialog, connection badge, timer, error toast. **[BASE]** Live mode was an iframe inside the split layout.
* Tavus CVI mode: **[BASE]** present (TavusVideo/TavusTranscript, `/api/tavus/start|end`, paid); **[WT]** deleted.

### Markets (themes markets/clear)
Header + MarketStatusBar, group pills (India/Global/... `aria-pressed`), IndexCard list (opens StockDrawer), "ARIA insight of the moment" (breadth bar, ask chips), SectorHeatmap (tiles expand to stock chips), MoversTable (gainers/losers/active pills), Watchlist (combobox search, add/remove), NewsFeed (search, filter pills + more + company select, daily-asks, Q&A panel, paginator, article modal with sentiment, related stocks, Ask ARIA), PersonalPanel "Your money" (assets donut, goals progress, cash-flow chart, "Your equity today"), StockDrawer (dialog: score, price chart Area/Candles + range, key stats, ask chips, add to watchlist), Provenance badges.

### Explore
InstrumentSearch (type chips x9, combobox + listbox, skeleton/empty), Watchlist (list + remove), InstrumentDrawer (quote, risk tags, chart + ranges, key facts, SIP simulator (amount/years inputs + Run), AskPanel (suggested questions + free text, log region), watchlist toggle, disclaimer line).

### Research reports
Create form (CompanySearch combobox + "Generate research report"), saved reports list grouped by symbol (open, download HTML/MD/JSON, open in new tab, regenerate, delete, show older versions), report viewer iframe (sandboxed) with kind select, "All reports" back, forecast-validation status (Run validation / Refresh / Retry).

### Company intelligence
Analyse form (company input + suggestions, example chips), progress status, result: score ring, "What ARIA concluded", factor table, conflicts, evidence accordions, news, management commentary; "New search"; Sentiment scorer (textarea, "Use an example", "Score text").

### Profile
Dashboard (health score ring, goals, net worth etc.), "What ARIA remembers" (Edit/Forget per fact), Quick-form wizard (5 steps: nav buttons, completeness progressbar, fields with range validation, Back/Skip/Save & next), "Delete all my finance data", Transactions (add form: Date/Category/Amount/Merchant/Channel; Add; Load sample data; Clear all), Statement upload (file -> preview -> Import/Cancel), Spending insights (Show/Hide, ask chips, charts).

### Progress
Heading, empty banner + "Ask ARIA to explain a concept" button, mastery list with bars.

### Feedback **[WT]**
Name, Email, Category select, "How did you hear" select (+ "Other" text), Message textarea (10-5000 chars), Send; status check `GET /api/feedback/status`; success state "Send another response"; notice when email not configured (button disabled).

### Settings
Theme radiogroup (4 cards), Colour mode radiogroup (markets/clear), "Adapt tone to how I feel" checkbox, "Forget how I like to talk" (window.confirm), About + disclaimers link.

### Disclaimers
Header, table-of-contents, sections (purpose, free services, ... contact link to feedback **[WT]**).

## 6. Backend endpoints consumed by UI (VERIFIED `web/src/versions/v2/api.ts`)
chat, chat/history, chat/clear, transactions (parse/import/list/add/clear/sample/insights), voice/transcribe, audio/{token}, profile (get/summary/update/delete/style), progress, quiz/answer, research/reports (list/html/download/regenerate/delete), research/validation, research/intelligence, research/sentiment, instruments (search/browse/quote/...), markets/*, auth/*, live/ws, feedback, feedback/status **[WT]**; `tavus/start|end` **[BASE]** only.

## 7. Live-DOM counts
_pending: filled by matrix probe_

## 8. Not covered / blocked
_pending_
