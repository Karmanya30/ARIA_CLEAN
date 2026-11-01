# Root-cause analysis: the 12 baseline questions that fell through to the general model

Data: `evaluation/intent_understanding/results/fallthrough_12.txt` (generated), `fallthrough_after.txt`. "Fell through" means the rules placed nothing, so the question reached `_general_reply`, which answers from the model's memory with no data behind it.

## Common finding: retrieval was never attempted
For all 12 questions the failure happened **before** any retrieval or tool: no capability was selected, so there was no empty retrieval, tool exception or timeout to investigate (three of the ten candidate causes you listed, "tool execution exception", "empty retrieval result" and "timeout", did not occur in any case). The causes were: rule gaps (incorrect intent classification) for 9 questions, a missing "ask before advising" policy for 2, and a flaw in my test harness for 1. The final generated response is not reproduced per question because both language-model providers were out of free quota at the time of writing; by construction the general path produces text without evidence, which is the failure.

## The 12 cases

| # | Question (id) | Expected | What the rules saw | Why it fell through | Category | Fix (general pattern, not the exact words) | Regression test |
|---|---|---|---|---|---|---|---|
| 1 | kitna kharch hua food pe (I0012) | finance | normalised to "how much spend hua food pe": no finance keyword, no intent pattern | Hinglish spending question not covered by any pattern | rule gap | first-person money statements/questions with a money word (`_PERSONAL_MONEY`) route to finance | `test_rules_now_place_the_question` |
| 2 | what does NAV mean (I0042) | tutor | "what does ... mean" is not in the concept-question pattern; "NAV" is in no keyword bucket; the lookup needs a proper noun | wrong fallback policy for a definition request | rule gap | `is_finance_concept_question` (definition forms + a finance term, impersonal) routes to the tutor; `_CONCEPT_QUESTION` also accepts "what does X mean" | `test_finance_concepts_go_to_the_tutor` |
| 3 | markets kaisa chal raha hai aaj (I0069) | market | "markets kaisa" not in the market terms | Hinglish market phrasing | rule gap | added Hinglish and "how are the markets" phrasings | `test_rules_now_place_the_question` |
| 4 | compare it with TCS (I0153) | equity research (or clarify) | ticker TCS found, but no research phrase | a comparison naming a company was not an equity question | rule gap | company + compare/versus/vs routes to company analysis | same |
| 5 | how much do I need monthly to reach 1 crore in 20 years (I0208) | finance | has "I", an amount and years, but no "goal" word | goal calculation without the word "goal" | rule gap | amount + years + reach/achieve/build/accumulate in a first-person question is a goal calculation | same |
| 6 | sell everything now? (I0236) | clarify | no company, no earlier topic | no policy for a decision with nothing to decide about | missing clarification policy | `decision_without_subject`: ask which holding, answer nothing | `test_a_decision_with_nothing_to_decide_about_is_asked_about` |
| 7 | I earn 80k and spend 50k, how much can I save (I0002) | finance | a question, so not a "statement"; "80k" and "save" are in no keyword list | personal money question with abbreviations | rule gap | `_PERSONAL_MONEY` | same as 1 |
| 8 | define asset allocation (I0043) | tutor | "define" matches the concept pattern but only finance-keyword questions were converted to the tutor | concept question outside the finance keyword list | rule gap | as 2 | same as 2 |
| 9 | dollar vs rupee today (I0066) | market | "rupee vs" is a term, "dollar vs rupee" was not | currency phrasing | rule gap | added currency phrasings | same as 3 |
| 10 | how did Bitcoin, Ethereum and gold do this month (I0222) | data lookup (or market) | "do ... this month" is not a data word, so the lookup never ran | data-question detector too narrow | rule gap | performance phrasings added to the data-question detector | `test_named_data_questions_reach_the_lookup` |
| 11 | Kaynes ka revenue kitna hai? (I0242) | data lookup | in the real system this question WORKS (verified live on 1 Nov: the catalogue finds Kaynes and answers from Screener.in data). The benchmark stub required a capitalised word that was not the first word | **harness flaw**, not an ARIA failure | test artefact | the stub now asks the real catalogue; the first word counts as a name when it is not a question word | same as 10 |
| 12 | should I sell it (I0248) | clarify (or company analysis) | no company, no earlier topic in a single-turn run | no policy for a decision with nothing to refer to; with an earlier company the existing pronoun logic already resolves it | missing clarification policy | as 6 | same as 6 |

## Evidence sufficiency gate (implemented)
1. **No-evidence answer:** a data question that names a thing (a capitalised or non-ordinary word) which neither the instrument catalogue nor a web search can answer now gets an explicit "I couldn't find reliable data for that, so I won't guess a figure" (`lookup.no_data_answer`), instead of falling to the general model. The response carries `gate: no_evidence` and no figure (regression test).
2. **Ask before advising:** a buy/sell/hold instruction with no referent is answered with one question (`gate: missing_subject`).
3. **Believable names only:** a single ordinary English word that the user did not capitalise is no longer accepted as a company or fund name ("what is a bond yield" had matched *Bondada Engineering*, "intraday trading tips" matched *Tips Music*). Found because the corrected benchmark stub exercised the real catalogue; regression test added.
4. **Not changed:** genuinely non-financial questions still reach the general model (negatives in the regression tests and the challenge set: "I spend hours reading novels", "what does the word ubiquitous mean", "hold the door please").
5. Existing: the post-generation number check (`modules/qa/trust.py`) and per-part verification for multi-part answers.
Not implemented: a per-answer freshness check (the data date is shown, but there is no rule that refuses a stale quote) and retry through an alternative path when a pipeline returns nothing; both are listed as next steps.

## Effect, with the contamination stated plainly
| Baseline A | Unacceptable outcomes (n=259) | Of which fell to the general model | Wrong-route |
|---|---|---|---|
| before the fixes | 45 | 12 | 43 |
| after the fixes | see FINAL_BENCHMARK_RESULTS.md | 1 | |

The fixes were written looking at these exact questions (dev and test), so the improved accuracy on benchmark_v1 is **not** a held-out measurement of the rule changes. The fair check is the challenge set: 39 new questions of the same kinds written after the first fix round. On it, the old rules scored 19 of 39 (48.7%); the first post-fix run scored 31 of 39 (79.5%) before any further change; and the old rules had also wrongly taken 2 of the 7 negatives ("I spend hours reading novels", "I earn my keep by writing code"), which the new rules no longer do. The eight challenge misses of that first run were then used to refine the patterns, so the final 39 of 39 is a regression result, not a generalisation result.
Side effects found and fixed: `finance_statement` treated any first-person "I spend ..." as a saved spending fact (now requires an amount); the router's concept override missed "what does X mean".
