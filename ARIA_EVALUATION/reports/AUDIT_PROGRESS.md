# Audit progress (as of 2026-11-13)

Fixes are merged to `main` of Karmanya30/ARIA_CLEAN (PRs #52 to #92). The user's own version without the project partner's changes is kept at `D:\ARIA_local` (branch `our-version`, also pushed to GitHub as the branch `our-version`, not merged into main).

## Done (merged, tested)
| Finding | What was done | PR |
|---|---|---|
| PERF-01 | Instrument search 1.4 s to about 45 ms | #52 |
| REL-01 | Speech/sentence models load offline-first; speech model warmed at startup | earlier, #74 |
| SEC-01 | No remote Markdown images or off-source links from web answers | #73 |
| SEC-02 | Live sockets: own caps, idle close, keep-alive ping | #54 |
| SEC-03 | Deleting a chat forgets it; "Erase all my data" | #53, #58 |
| SEC-04 (part) | Private mode refuses non-loopback bind, write guard, Docker defaults to accounts, log redaction | #73 |
| SEC-05, SEC-08 | Email-verified sign-up, uniform answers | #73 |
| SEC-06, SEC-07, SEC-09 | CSP and headers, API reference hidden in accounts mode, RSS link check | #73 |
| FIN-001 to FIN-007, FIN-009 | 80C eligibility, tax surcharge, negative deductions, sub-month tenure, unknown surplus, goal with no time, usable budget, anomaly flags | #59, #69 |
| AW-01 to AW-09, AW-11 | No double run, honest failed parts, LLM timeouts, degraded reply not 500, guard cooldown, per-part evidence, session eviction, context in worker threads, dead code | #60, #68 |
| RAG-01, 02, 03, 05, 07, 08 | Strict-mode figures, general-answer note, number words, old-fact recall, warnings | #68, #90, #92 |
| UV-001, 002, 004, 005, 006, 007 | Question in prompt, EMI misread, delete forgets, acronyms not tickers, natural phrasings, Hinglish/index misspellings | earlier, #55, #53, #87, #89, #88 |
| UX-01, 02, 04, 06 to 09, 11 to 13 | Meeting header fits narrow windows, skip link, clear-chat confirm, titles, stat names, dialog focus, 44 px targets, route rewrite, rate-limit message | #70 |
| UX-05 (part) | Plain avatar load error | #91 |

Also fixed during this work: routing default is the adaptive hybrid (H); finance-only gate removed (it refused small talk and news); news and market questions return real headlines; launcher works in accounts mode; profile database migration (goal, horizon_years).

## Open
- AW-10 live turn cancel does not stop the pipeline thread (needs a per-turn cancel token)
- RAG-06 memory retrieval speed at 400+ turns; RAG-09, 10, 11 (not yet read in detail)
- UX-03 navigation as real links; UX-05 full self-hosting of the avatar's CDN modules; UX-10 focus ring and drawer focus trap; UX-14 duplicate source tree
- FIN-008 spend forecast does not reproduce a flat history
- SEC-04 remainder: owner ids are not minted server-side or required to be long
- Companies Zomato and Paytm are not resolved
- Old PRs #10 to #16 are still open on GitHub (their changes are in main); closing them needs the user
- Not re-run: the eight audit agents against the final code, so the other reports still describe the old state
- Accounts browser suite (`e2e-accounts`) has outdated locators

## Test state when this was written
Python suite 1425+ passing; browser suite 57 of 57 (GPU server on port 8010 must be stopped for the avatar specs).
