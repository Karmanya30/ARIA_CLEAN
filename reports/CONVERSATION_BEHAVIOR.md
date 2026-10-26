# Conversational understanding fixes

ARIA now treats ordinary conversation as conversation, rather than trying to turn every message into a financial task or lesson.

## Confirmed causes

- No dialogue handling existed for acknowledgements, confirmations, disagreement, requests to continue or requests for a simpler explanation. These replies entered keyword routing, generic teaching or emotion-based responses.
- Substring keyword tests confused unrelated words with finance terms: `taxi` contained `tax`, and `spaceship` contained `sip`. Generic words such as `analysis` and the verb `share` also launched financial paths.
- The tutor fallback explicitly required a finance connection, four labelled sections and a check question even for unrelated questions.
- Domain categorization still influenced tutor routing despite no longer being an appropriate reason to reject a valid general question.
- Financial confirmation used a prefix match: a qualified reply beginning with “yes” could confirm an update.
- Voice prompts still pushed general topics back toward money. Cached Tavus personas could retain the earlier policy.
- Provider output cleanup changed foreign currencies to rupees and appended punctuation, which could corrupt general explanations or code.

## Implemented behavior

| User reply or request | Behavior |
| --- | --- |
| `ok`, `got it`, `cool`, `hmm`, `theek hai`, an acknowledgement emoji | Brief acknowledgement; no definition, quiz, financial workflow or repeated help invitation |
| `ok` after a specific conversational offer | Uses the preceding offer to continue the conversation |
| `yes please`, `go ahead`, `continue` | Uses both sides of the recent exchange; asks a focused question if no referent exists |
| `why?`, `explain simply`, `I don't understand`, `matlab` | Uses the previous exchange for clarification |
| `no` after an explanation | Uses context to understand disagreement rather than treating every “no” as cancellation |
| `no thanks`, `not now`, `cancel` | Respects the request to stop |
| `ok` while income or another financial input is missing | Keeps the pending question without inventing an amount |
| `yes` to an explicitly proposed profile update | Preserves the existing financial confirmation workflow |
| `yes, but don't change it` | Does not confirm a profile update based on the affirmative prefix |
| A coding, writing or translation task containing finance vocabulary | Answers the requested task without launching an unrelated financial workflow |
| An unmatched educational question or missing tutor index | Falls back to a direct general answer without a forced finance connection |

Whole-reply matching keeps longer messages such as “ok, explain SIP” available for normal task routing. Financial plurals remain recognized. The general system instructions retain safety, privacy, evidence, authorization and financial-risk rules. A domain category is advisory metadata, not a safety decision.

## Files

- `shared/dialogue.py`: conversation acts, exact confirmation interpretation, explicit general-task detection and shared general conversation instructions.
- `core/orchestrator.py`: contextual short replies and general-task routing; removal of the tutor category gate.
- `shared/intent_classifier.py`: word boundaries and financial plurals.
- `modules/finance/pipeline.py`: whole-reply confirmations.
- `modules/tutor/pipeline.py`, `ai/llm/prompt_templates.py`: natural fallback when no financial concept is matched; graceful handling of missing tutor files.
- `ai/llm/groq_client.py`: preserves currencies, code and formatting for general responses.
- `api/routes/live.py`, `ai/llm/spoken.py`, `api/routes/avatar.py`: consistent voice instructions and versioned persona cache.
- `shared/domain_guard.py`: documents advisory categorization correctly.
- `tests/test_dialogue.py`: synthetic conversational scenarios; supporting memory, language and voice tests updated where behavior or prompt ownership changed.

No new framework, external repository, model subscription or environment variable is needed. Existing user data, model selection and `.env` remain unchanged. Restart the backend to load the new code. A new Tavus session refreshes a cached persona when its conversation policy is outdated.

## Validation

- Broad regression: **433 passed** across conversation, routing, financial workflows, tutor, memory, chat API and voice tests (`dialogue-final-regression.txt`).
- Subsequent domain, voice-cache, memory and general-format checks: **118 passed** (`dialogue-final-checks.txt`).
- Final additional conversation, plural, formatting and voice checks: **100 passed** (`dialogue-latest-checks.txt`).
- The first run exposed an unchanged, timing-sensitive tone-engine speed test; it passed when rerun alone. A brittle memory test that inspected function source was replaced with a check of the actual system prompt passed to generation.

These tests use synthetic conversations, temporary databases for the new scenarios, mocked model replies, and fake Tavus calls. They verify routing, context delivery, persistence and confirmation behavior. They do not establish human-level intelligence or guarantee the quality of every live provider response. No private conversations were used as fixtures or sent for evaluation. No production deployment was performed.
