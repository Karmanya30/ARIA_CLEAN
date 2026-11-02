# Chat reply style, message actions and conversation history

What changed, why, how it was verified, and what is not done. Facts only; nothing here was measured that is not stated as measured.

## 1. Unsolicited quizzes and empty Cognitive / Functional / Causal headings

**Symptom:** an explanation of a concept ("what is a SIP") ended with a multiple-choice question and a Submit button nobody asked for, and the reply showed Cognitive / Functional / Causal headings, sometimes with nothing under them.

**Root cause (two separate causes):**
1. `modules/tutor/orchestrator.py` generated a quiz whenever the learner had not seen the concept before (`first_time`), or whenever the teaching policy picked `ask_quiz`. The rule was added so the Progress page would fill up; it made every first explanation end in a test.
2. `modules/tutor/pipeline.py` built the reply as `Cognitive: ... Functional: ... Causal: ...`, and `ResponseCard.tsx` turned those labels into cards. A model that wrote the labels itself, or left a section empty, produced stray `**` and empty headings.

**Fix:**
- A quiz is produced only when the learner asks (`force_quiz`, from "quiz me", "test my knowledge", "practice questions").
- `taxal_text()` joins the non-empty sections as plain paragraphs and strips labels and `**`.
- `ResponseCard` removes those internal labels even if a model writes them, and renders everything else as Markdown.
- The v1/v2 Markdown renderer lacked `remark-gfm`, so tables showed as raw pipes; it is now added (`web/package.json`). The `pre-wrap` spacing on plain replies is removed.

**Before / after:** before, "what is a SIP" returned labelled cards plus a quiz widget. After, it returns paragraphs only; "quiz me on SIP" still returns the quiz.

**Tests:** `tests/tutor/test_reply_style.py` (the teaching policy always votes "quiz" and none is produced; labels and `**` removed; empty sections skipped), `web/e2e/reply-style.spec.ts` (five questions through the real UI with a stubbed answer: table rendered, no Submit, no label headings, action buttons present).

## 2. Message actions

Under each answer: copy, regenerate (last answer), helpful / not helpful (stored on the saved turn, returned by both history endpoints, survives reload), and a Stop button that cancels the wait. The assumed return is shown next to projections with "estimates, not guaranteed returns".

**Limits:** the API returns one JSON reply, so there is no token streaming; Stop stops the wait, the server still finishes and saves the answer.

## 3. Conversation history

**Audit before the change:** conversations and turns were already stored per owner in the database (`chat_conversations`, `chat_turns`), and the account / private-mode owner checks existed. Missing: titles, pin / archive / delete state, a list and search API, export, and any UI. The active conversation id lived only in the browser, which is why a new device or a new login started empty.

**Built:**
- Columns `title, pinned, archived, deleted_at, created_at, updated_at` on `chat_conversations` and `rating` on `chat_turns`, added by an automatic migration that fills dates for existing chats and titles from the first answered question. No rows are dropped.
- `/api/conversations`: list and search (paginated), paged messages, rename / pin / archive, soft delete, JSON and Markdown export, per-message rating. Every query is filtered by owner; another owner's id is a 404, and in account mode a mismatched `owner_id` is a 403.
- UI: a Chats button (Chat page and the live meeting) opens a left panel that pushes the page and the avatar aside, with date groups, search, row actions, and a draggable divider (width remembered). Opening a chat asks how to continue: chat, voice or video call. The avatar's right-hand chat can also be resized by dragging.

**Verified in a real browser** (two separate browser contexts as two devices): refresh keeps the chat, a second device lists and opens it, rename / pin / rate / delete propagate, the panel works inside the live meeting, both dividers drag. Backend tests cover persistence, second device, logout and login, cross-account access, paging, search, export, migration.

**Not verified:** a real microphone call in the live meeting (history capture from a spoken session), touch dragging.

## 4. Chat UI templates (assistant-ui, shadcn chatbot template, Vercel ai-chatbot, CopilotKit)

These were assessed from their documented designs, not cloned or run in this repository. Treat the table as a recommendation to check, not a measurement.

| Option | What it gives | Why it was not adopted wholesale |
|---|---|---|
| assistant-ui | Message primitives, action bar (copy, reload, feedback), streaming, branch picker | ARIA's turns are not token streams, and its message shapes (domain, blocks, quiz, report) are custom; adopting the runtime would mean rewriting ChatTab, history and the live meeting |
| shadcn chatbot template / Vercel ai-chatbot | A full app (auth, history sidebar, Next.js) | Different framework and backend; ARIA already has accounts, history and a Vite UI |
| CopilotKit | Agent-in-app copilot framework | Solves an in-app agent problem ARIA's pipeline already solves |

**Patterns borrowed (re-implemented natively):** a per-message action bar, history in a left sidebar with date groups, rating stored per message, an explicit Stop control.

## 5. Not built

- A "response mode" decision (brief / table / detailed). The prompts already adapt to what is asked, and tables now render; a central decision would touch every pipeline's prompt and was judged not worth the risk without evidence it is needed.
- Token streaming (needs a streaming endpoint through the unified pipeline and the grounding step, which checks the finished answer).
- The UI still loads a whole chat at once; the paged messages API exists.
- Tab-key focus inside the live meeting stays inside the meeting, so the history panel is mouse-reachable there.
