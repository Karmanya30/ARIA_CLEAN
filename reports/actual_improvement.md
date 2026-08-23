# ARIA Actual Improvement Plan

Generated on: 7 August 2026

Purpose: This document lists the real improvements needed to make ARIA feel like a professional AI assistant instead of a manual academic project demo.

## 1. Avatar Improvements

Current problem:

- The avatar looks anime/cartoon-like.
- It does not feel professional or finance-assistant suitable.
- Lip sync is weak or missing.
- It mostly looks like a moving 3D model, not a speaking assistant.
- The avatar does not add trust, clarity, or impact.

Why this is happening:

- The current `interface/avatar/model.glb` is the visual identity. If that model is cartoon-like, the whole avatar will look cartoon-like.
- TalkingHead can animate a GLB model, but it cannot make a poor avatar asset look professional.
- Lip sync depends on browser audio permission, HeadAudio loading, AudioWorklet support, and correct mouth morph targets in the model.
- The current lip sync is audio-signal based, not phoneme/viseme-timestamp based.
- The iframe requires a click before audio playback because browsers block autoplay.

Required improvements:

- Replace the current GLB with a professional realistic avatar.
- Use a model with proper facial blendshapes/morph targets for mouth movement.
- Use a formal assistant style: realistic face, clean clothing, neutral professional expression.
- Improve lighting, camera angle, background, and framing.
- Add natural idle behavior: blinking, subtle head movement, eye contact.
- Add expression states:
  - Neutral for normal answers.
  - Concerned for risk warnings.
  - Confident for recommendations.
  - Explaining for tutor mode.
- Add avatar diagnostics:
  - Model loaded.
  - Audio loaded.
  - AudioContext running.
  - Lip-sync module loaded.
  - Morph targets detected.
- Add fallback mode when avatar fails:
  - Professional audio player.
  - Transcript.
  - No broken or frozen 3D view.

Best implementation path:

1. Short term: replace `model.glb` with a professional Ready Player Me/VRM/GLB avatar that supports mouth morph targets.
2. Short term: remove cartoon/anime styling from the avatar scene.
3. Medium term: generate viseme timings from TTS audio and drive the mouth directly.
4. Medium term: add facial expressions based on answer type.
5. Long term: use a production avatar stack or API if the project needs a truly polished virtual human.

Priority: Critical.

## 2. Text Size and Visual Design

Current problem:

- Text feels like a project output, not an assistant interface.
- Cards can feel too heavy and academic.
- Section labels make every answer look manually formatted.
- The app does not feel conversational enough.
- Some text is likely too large or too rigid for a chat assistant.

Required improvements:

- Reduce oversized headings inside the app.
- Use compact assistant-style message bubbles instead of report-like blocks everywhere.
- Keep section labels, but make them subtle.
- Use readable body text around 14-16px.
- Use smaller captions for metadata like domain and company.
- Avoid too many decorative cards.
- Make spacing tighter and more professional.
- Use a quiet finance-assistant color palette.
- Make the chat the main experience, not the tabs and controls.

Suggested UI direction:

- Page title: small `ARIA` header, not a huge project title.
- Chat messages: clean assistant/user bubbles.
- Response sections: subtle dividers or small labels, not large colored boxes.
- Metadata: small inline badges.
- Profile/progress panels: simple forms and progress rows.
- Avatar: placed beside or above assistant response only when working properly.

Priority: High.

## 3. Make It Feel Like Talking to an Assistant

Current problem:

- The user has to manually choose modes.
- The app asks the user to understand modules.
- Example prompts are useful, but the experience still feels technical.
- Answers are structured, but not always conversational.
- Voice/avatar flow feels disconnected.

Required improvements:

- Remove the feeling that users are selecting a project module.
- Let the assistant decide automatically.
- Keep module routing internal.
- Replace technical labels with natural assistant language.
- Add short acknowledgements before detailed answers.
- Ask follow-up questions when required information is missing.
- Keep memory visible but not complicated.
- Make finance profile collection conversational.

Examples:

- Instead of: `Domain: finance`
- Use: `Used your financial profile`

- Instead of: `Conversational Mode`
- Use: voice/avatar toggle with an icon.

- Instead of asking users to fill a large profile form first:
- Ask: `What is your monthly income and EMI? I can estimate a safer SIP from that.`

Priority: Critical.

## 4. Reduce Manual and Complex Workflow

Current problem:

- The user needs to know what to ask.
- Profile inputs are separate from chat.
- Quiz flow is incomplete from the user perspective.
- Voice input requires multiple actions.
- Avatar playback requires another click.

Required improvements:

- Convert profile setup into a guided chat flow.
- Auto-detect missing fields and ask only for those fields.
- Add quick chips for common follow-ups:
  - `Show safer option`
  - `Explain simply`
  - `Give monthly plan`
  - `Show risks`
  - `Quiz me`
- Make quiz answers clickable.
- Record tutor quiz answers directly in the UI.
- Add one-click voice ask.
- Add one-click replay audio.
- Reduce repeated buttons.
- Hide developer/debug details unless expanded.

Priority: High.

## 5. Chat Answer Improvements

Current problem:

- Answers can feel like generated report sections.
- The assistant should sound more natural.
- The format is useful, but too visible.

Required improvements:

- Start with a direct answer in 1-2 lines.
- Then show compact sections only when useful.
- Use numbers first for finance/equity answers.
- Use source/timestamp when market data is used.
- Add "what I need from you" when data is missing.
- Avoid long generic disclaimers.
- Keep risk warning short and practical.

Better answer format:

1. Direct answer.
2. Key numbers.
3. Recommendation.
4. Risk or caveat.
5. Follow-up action.

Priority: High.

## 6. Finance Module Improvements

Current problem:

- Finance logic exists, but user experience is still rough.
- The assistant needs better guided planning.
- The user should not have to understand inputs manually.

Required improvements:

- Add guided financial onboarding.
- Ask for monthly income, EMI, rent, savings, dependents, emergency fund, and goals step by step.
- Add goal planning:
  - Emergency fund.
  - SIP goal.
  - Tax saving.
  - Debt repayment.
  - Insurance planning.
- Show budget as a simple monthly allocation.
- Add editable assumptions.
- Add confidence/explanation for risk profile.
- Add warnings when advice is based on incomplete data.

Priority: High.

## 7. Tutor Module Improvements

Current problem:

- Tutor backend is good, but the UI does not fully feel adaptive.
- Quiz answers are not fully integrated into the chat experience.

Required improvements:

- Add clickable quiz options.
- Record quiz answers immediately.
- Update mastery after each answer.
- Show next suggested concept.
- Add simple/medium/advanced explanation controls.
- Use examples from Indian finance.
- Add revision reminders.
- Make progress tab simpler and more visual.

Priority: Medium-High.

## 8. Market and Equity Research Improvements

Current problem:

- Market/equity answers depend on external data, but the UI does not clearly show freshness.
- Users need trust signals.

Required improvements:

- Show data source and timestamp.
- Show if data is delayed or unavailable.
- Add retry/fallback message for failed data sources.
- Add source links where possible.
- Add peer comparison for companies.
- Add fundamental ratio table.
- Add chart for price trend.
- Add news sentiment explanation.
- Avoid direct buy/sell advice.

Priority: Medium-High.

## 9. Voice Experience Improvements

Current problem:

- Voice exists, but it feels bolted on.
- TTS and avatar are not seamless.

Required improvements:

- Make voice input a single microphone button.
- Show recording, transcribing, thinking, and speaking states.
- Add stop/replay buttons.
- Use a more professional voice.
- Add voice speed control.
- Clean long answers before TTS.
- Use short spoken summaries instead of reading full detailed text.

Priority: High.

## 10. App Structure Improvements

Current problem:

- The app looks like multiple project modules exposed to the user.
- A real assistant should hide system complexity.

Required improvements:

- Main screen should be chat-first.
- Move profile and progress into a side panel or settings drawer.
- Hide module names from normal users.
- Keep technical route/domain info in a debug expander only.
- Add persistent left sidebar:
  - New chat.
  - Financial profile.
  - Learning progress.
  - Settings.
- Add conversation history list.

Priority: Medium.

## 11. Professional Polish

Required improvements:

- Replace emoji-heavy interface with consistent icons.
- Use consistent typography.
- Use consistent spacing.
- Improve loading states.
- Improve error states.
- Add empty states that guide the user naturally.
- Add source and confidence indicators.
- Add mobile responsiveness testing.
- Add accessibility labels.
- Add dark/light mode consistency.

Priority: Medium.

## 12. Technical Improvements

Required improvements:

- Add end-to-end UI tests.
- Add browser tests for avatar rendering.
- Add avatar health checks.
- Add cache expiry for market data.
- Add structured logging.
- Add API failure monitoring.
- Add deployment health check.
- Add model artifact check at startup.
- Add CI pipeline.
- Add data freshness validation.

Priority: Medium.

## 13. Immediate Action List

Do these first:

1. Replace the avatar model with a professional realistic avatar.
2. Add avatar diagnostics so failures are visible during development.
3. Redesign chat messages to feel like an assistant conversation.
4. Reduce large cards and heavy section formatting.
5. Make text smaller, cleaner, and more readable.
6. Hide technical module/domain details from normal UI.
7. Convert profile collection into guided chat questions.
8. Add clickable tutor quiz answers.
9. Show market/equity data source and timestamp.
10. Improve voice controls with clear recording/transcribing/speaking states.

## 14. Demo Recommendation

Until the avatar is fixed, do not make it the main highlight in a formal demo.

Recommended demo flow:

1. Show chat-first assistant.
2. Show finance calculation with profile memory.
3. Show tutor explanation and quiz.
4. Show market/equity data with real numbers.
5. Show voice output.
6. Show avatar only as experimental, or disable it until the professional model and lip sync are improved.

## 15. Final Priority Ranking

Critical:

- Professional avatar replacement.
- Assistant-like conversation flow.
- Reduce manual complexity.

High:

- Text size and visual design cleanup.
- Better voice flow.
- Guided finance profile.
- Clickable tutor quizzes.

Medium:

- Data source transparency.
- Market/equity charts.
- UI testing.
- Deployment polish.

Low:

- Extra animations.
- Decorative visuals.
- Marketing-style landing page.
