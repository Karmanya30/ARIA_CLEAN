# Failure analysis

Source: `evaluation/intent_understanding/results/failure_analysis.txt` (generated from the stored rows).

## A. Why the baseline misroutes (dev + test, n=259: 45 unacceptable outcomes = 43 wrong-route + 2 needless questions)

| Cause | Count of the 45 failures | Example |
|---|---|---|
| A keyword/regex picked a neighbouring module | 20 | "what does expense ratio mean" or "quiz me on mutual funds" going to personal finance (tutor -> finance was the most common confusion: 10 cases) |
| Nothing matched, so the question fell to the general model, which has no data behind it | 12 | "how much do I need monthly to reach 1 crore in 20 years", "markets kaisa chal raha hai aaj" |
| A multi-part question ran only one module | 9 of 20 multi-intent items | "What is SIP and how much SIP can I afford on my salary?" |
| The tone/dialogue layer took a real question | 2 | "show RSI and MACD for Reliance" got a supportive-tone reply |
| A needless clarification | 2 | |

Separately, 10 items expected a clarifying question and did not get one (for example "sell everything now?"); the benchmark accepts a general reply for most of them, so only some are among the 45 above (they appear under "fell through").

Categories with the most failures: multi-intent (9 of 20), tutor (7 of 19), Hinglish (4 of 10), calculations (4 of 10), follow-ups (6 of 38).

## B. What each new layer fixed and broke

* **B, Semantic Router (fallback mode):** consulted on only a handful of questions (the rules already place most). On test it fixed none and broke two: "how does leverage affect real estate returns" (A: general, which was acceptable; B: equity research) and "convert 5 lakh rupees to crore" (B: market). The encoder is small and the example sets short, so similar-sounding routes are confused (SIP the concept versus SIP for my salary). In "override" mode it fixes 6 and breaks 10 on test, because it overrides rules that were right.
* **C, LangGraph with rule-based splitting:** fixed "Quiz me on SIP and then tell me my savings rate" and "What is beta, and what is the beta of Tata Motors" on test and broke nothing there; on dev it fixed one and broke one. The first version of its rule labeller lacked the orchestrator's "concept question means tutor" override, so "What is a SIP and how much SIP can I afford" was not split; found by a live check and fixed, with a regression test. Splitting only happens when both halves are clauses of at least three words that the rules place in different modules.
* **D, structured understanding + router + graph:** on dev fixed 15 and broke 5. Fixed: tutor/finance confusions ("quiz me on mutual funds", "what does NAV mean"), several Hinglish and calculation questions. Broke: the two adversarial prompts ("ignore previous instructions...", "pretend you are my SEBI adviser...") which it answers with a clarifying question (arguably safe, scored as wrong because the benchmark expects the general reply), "should I buy options on Nifty tomorrow" (routed to finance), "is crypto a good investment" (market), and the gold-ETF multi-part question.
* **E, hybrid:** on dev fixed 6 and broke 3 (two of them the same adversarial prompts, plus a Maruti/Mahindra comparison routed to market).

## C. Remaining failure categories (all variants)

1. Unsupported topics (technical analysis, options trading): no variant refuses honestly, because ARIA has no such feature and no "unsupported" route exists; the answer comes from the general model. Needs a product decision, not a router.
2. Adversarial and role-override prompts: the structured layer sometimes asks a question instead of answering; the content safety of the final answer was not evaluated here.
3. Same-name entities ("price of Tata", "is SBI good"): handled by asking only when the model flags ambiguity; entity extraction F1 for D on dev is 0.52 (names are matched by substring, which is strict).
4. Follow-ups that depend on what the person holds ("should I sell it"): the model usually routes to finance with 0.88 confidence without checking that the user holds the stock (SUSPECTED risk; the benchmark counts finance, equity research or clarify as acceptable).
5. Hinglish: improved by D, still the weakest category.

## D. Findings outside routing, found while building this

* **Safety (fixed):** "I am thinking of hurting myself" and similar sentences reached the general model; the crisis detector missed 8 of 12 realistic phrasings. Widened and regression-tested (12 of 12 now; the phrase "what is self harm insurance cover" also triggers the gentle care reply).
* **Deadlock (fixed):** parallel parts inside a turn deadlock on the per-conversation lock. ARIA's session state is not thread-safe, so parallel execution inside one turn needs a refactor first.
* **Provider schema:** strict structured output rejects free-form maps; entities are a typed list.
