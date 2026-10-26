# ARIA — Competitive Analysis

Research date: 17 October 2026 (Asia/Kolkata).

## ARIA | Competitive analysis

<div class="eyebrow">BTP / academic evaluation report</div>
# How is ARIA different?
## An evidence-based comparison with 12 competing platforms
**Prepared for:** project review, teacher discussion and viva preparation
**Research date:** 17 October 2026, Asia/Kolkata
**ARIA code baseline:** 49d071d, audit/system-review-20261016

### Executive finding
ARIA's most defensible contribution is an inspectable, India-focused application that combines personal-finance workflows, financial tutoring, market exploration and structured equity research. Its value lies in domain logic, persistent application state and evidence handling around an existing language model. It has not demonstrated superior general intelligence or investment performance over commercial competitors.

### Suggested positioning statement
> ARIA is an integrated financial learning and analysis prototype for Indian users. It combines deterministic financial calculations, persistent personal context, adaptive tutoring components and provenance-aware company reports in a developer-controlled application.

### What this report establishes
- Where ARIA's implementation differs from commercial products.
- Where the same capabilities already exist elsewhere.
- Which claims have repository or test evidence and which still need independent evaluation.
- How to demonstrate the project's contribution without overstating novelty.

**Evidence boundary:** This is a source-based product comparison and repository review, not a paid-account benchmark or an exhaustive survey of every financial product. Competitor availability can vary by plan, country and organization. [R01–R16; S01–S16]

**Reader guide:** Scope and architecture: pp. 2–3. Comparison matrix: p. 4. Competitor profiles: pp. 5–8. Differentiation: pp. 9–10. Demonstrations: pp. 11–12. Evidence and risks: pp. 13–14. Evaluation plan: p. 15. Viva answers: p. 16. References: pp. 17–20.

<!-- PAGE -->

## 01 | Scope and comparison method

## What is being compared?
The representative set covers four categories: AI research assistants (Perplexity, ChatGPT, Claude, Gemini); India-oriented research tools (Screener, Tickertape, Trendlyne, Moneycontrol); specialist/global tools (TradingView, Yahoo Finance, Alpha Spread); and an institutional reference point (Bloomberg Terminal). Twelve products provide a broad comparison; “all competitors” cannot literally be established in a finite report.

## Evidence rules
**Implemented:** visible in ARIA source or maintained implementation reports. This does not prove the feature works for every input. **Tested:** a recorded check exercised specified behavior. **Proposed:** a demonstration, experiment or improvement that has not been completed. **Vendor-documented:** a competitor describes the capability; this report does not independently certify its quality.

## Comparison dimensions
1. Primary user and problem being solved.
2. Financial data and geographic coverage.
3. Calculations, sources, assumptions and explainability.
4. Personal context, workflow state and learning support.
5. Reports, exports, integrations and deployment control.
6. Reliability, cost structure, privacy and measured limitations.

## Important controls
No competitor was scored using invented percentages or star ratings. No absence claim is inferred merely because a marketing page omits a feature. “Different emphasis” means the reviewed material describes a different workflow, not that the vendor cannot implement ARIA's behavior.

Official sources were checked during this report's research. Yahoo Finance's subscription page was available through its official search result, but direct page retrieval failed; its description is consequently narrow. Other cited pages were retrieved. Prices and precise plan quotas are intentionally excluded because they change and a comparable subscription basket was not purchased.

ARIA evidence is pinned to commit 49d071d. The workspace also contains a later, uncommitted removal of the redundant Explore category panel; it is outside the recorded full-suite checkpoint. Private databases, credentials and .env values were not used as report evidence. [R01, R02, R11]

<!-- PAGE -->

## 02 | What ARIA actually implements

## Four application areas
| Area | Implemented contribution | Qualification |
| Personal finance | Structured profile, budgets, goals, SIP/EMI and affordability calculations; statement imports and stored transactions. [R04, R05] | Tax scope and financial input assumptions require review; no verified bank-account synchronization. |
| Financial tutor | Concept retrieval, quizzes, learner-state tracking, DKT model code and a DQN teaching-action policy. [R06, R07, R16] | Resources/checkpoints affect operation. The teaching policy is trained against a simulated environment; real learner gains are unproven. |
| Market exploration | Search across instrument types, fuzzy company suggestions, watchlists, prices/charts and RSS news. [R11, R12] | Provider coverage, delays and availability vary. Catalogue reach is broader than report-engine coverage. |
| Equity research | NSE/BSE company resolution, deterministic valuation, fact ledger, verification findings and saved report versions. [R03, R13, R14] | A model-derived fair value is conditional on sources and assumptions; it is not an observed future price. |

## Architecture: where the work happens
<div class="flow">React interface → FastAPI → intent/dialogue routing<br>↓<br>Finance tools / tutor / market adapters / research pipeline<br>↓<br>SQLite state + calculation outputs + evidence ledger<br>↓<br>Groq-backed language generation, with a Gemini fallback → user-facing answer</div>

The language model contributes interpretation and narration. Stored records, import transactions, formulas and report evidence handling are application responsibilities. Provider fallback improves availability under some failures; it does not make model behavior identical or prove answer correctness. [R04, R05, R08, R15]

**Integration boundary:** The modules share an application and context infrastructure. A company report is not thereby proven to be a personalized suitability recommendation based on the user's complete finances. That cross-module decision would require explicit policy and separate validation.

<!-- PAGE -->

## 03 | Competitive landscape matrix

## Documented strengths and ARIA's relationship
| Product | Primary documented strength | How to position ARIA fairly |
| Perplexity Finance | Financial data, research and market explanations. [S01, S02] | Emphasize inspectable India-oriented application workflows, not exclusive access to financial data. |
| ChatGPT | General research plus financial workflows; connected Finances for eligible U.S. users. [S03–S05] | Compare a configured finance application with a broad platform; acknowledge current finance features. |
| Claude | Financial agents, Office workflows and data connections. [S06] | ARIA is a smaller educational system, not a superior institutional analyst platform. |
| Gemini | Source-based Deep Research with configurable inputs. [S07] | ARIA emphasizes maintained finance tools and application state. |
| Screener | Indian financial data, screening and document-focused AI. [S08, S09] | ARIA uses overlapping data and adds personal-finance/tutor workflows. |
| Tickertape | Instrument research, screens and investing discovery. [S10] | The distinction is the assembled learning and calculation workflow. |
| Trendlyne | Scores, estimates, alerts and backtesting features. [S11] | Do not equate ARIA's implementation tests with strategy-validation quality. |
| Moneycontrol | Financial news and subscription research. [S12] | ARIA emphasizes interactive tools and inspectable calculations. |
| TradingView | Chart-based analysis, alerts and scripting. [S13] | ARIA is complementary; its charts do not equal the full platform. |
| Yahoo Finance | Quotes, news, portfolio tracking and premium research. [S14] | ARIA adds custom workflows and also depends on Yahoo-derived data. |
| Alpha Spread | Intrinsic valuation, DCF tools and AI assistance. [S15] | DCF plus AI is not unique to ARIA; focus on implementation transparency. |
| Bloomberg Terminal | Professional research, analytics and financial workflows. [S16] | Use as a boundary comparison; ARIA is not an institutional replacement. |

**Reading this table:** These are qualitative workflow descriptions, not a completeness score or a ranking. The following pages explain overlaps, tradeoffs and the evidence behind ARIA's positioning.

<!-- PAGE -->

## 04 | ARIA versus Perplexity Finance

## What Perplexity already does
Perplexity documents financial-data access in Research and Labs, including prices, volume history and financial statements. Its Finance updates describe price alerts, an earnings hub, automated statement insights and access to Morningstar analyst research on U.S. equity pages. It should not be described as only a general web-search chatbot. Specific access and availability remain product-dependent. [S01, S02]

## Where ARIA differs
ARIA exposes its own finance-engine code, report fact structures, import/persistence behavior and tutoring implementation for inspection. A project reviewer can trace a stored profile field into a calculation, inspect assumptions, or reproduce a failed transaction-import test. This developer-level access is an advantage of possessing the implementation, not proof of stronger analysis. [R03–R08]

The most relevant proposed user journey is: understand a personal-finance concept, enter personal constraints, calculate an outcome, then explore a company and inspect its report assumptions in the same application. The individual capabilities overlap with competitor tools; the contribution is the chosen integration and audience.

## Where Perplexity is the more natural fit
For broad, current financial discovery and cross-source research, Perplexity is a relevant established alternative. Its documented financial features overlap substantially with ARIA's market/news and research interface. This report has not run matched queries to establish which system finds more complete or more accurate evidence.

## Defensible teacher answer
> Perplexity is a strong financial research competitor. ARIA's contribution is the inspectable combination of personal-finance tools, learner state and reproducible report logic for an India-focused prototype. We have not established a general research-quality advantage.

## What would prove an advantage?
Give both systems the same dated financial documents and questions. Measure source fidelity, numeric correctness, task completion, handling of missing data and user effort. Keep model/provider access and subscription constraints visible. A favorable demonstration is useful, but a cherry-picked example is not a benchmark.

<!-- PAGE -->

## 05 | ARIA versus ChatGPT, Claude and Gemini

## ChatGPT
ChatGPT documents cited deep research and finance workflows involving models, operating data and reviewable artifacts. Its Finances feature supports eligible U.S. users connecting account and credit information through Plaid and Experian, with spending and planning conversations. Therefore, “ChatGPT has no financial memory, tools or personal finance” is an outdated comparison. Availability and region matter. [S03, S04, S05]

ARIA supplies a particular India-oriented interface, schemas, formulas, persistence and report workflow as inspectable application code. ChatGPT can also perform calculations and build artifacts; the defensible distinction is a maintained domain implementation versus a broader platform with different configured capabilities. No superiority in reasoning or privacy has been established.

## Claude
Anthropic documents financial-service agents, spreadsheet/model work, Office add-ins and governed connections to research/data platforms. These overlap with financial modeling, citations and workflow automation. ARIA should not claim to be the only AI system with tools, auditability or financial agents. [S06]

ARIA is easier for its developer to modify at the domain-code level and has a specific tutoring/personal-finance integration. Claude is a serious alternative for professional document and spreadsheet workflows; a direct accuracy or cost comparison would require matched access and testing.

## Gemini
Google documents Deep Research that uses Google Search by default, can use selected additional sources and uploads, and produces research reports. Features and limits vary by account and plan. [S07]

ARIA packages finance-specific application behavior rather than asking the user to assemble each workflow from a general research request. Gemini is also used as an ARIA fallback provider: the project differentiates at the application layer while depending on external model capabilities. That dependency should be disclosed. [R15]

**Shared conclusion:** Good prompting, code execution, citations, memory and finance-related analysis are not exclusive inventions. ARIA must be evaluated on its particular workflow, reproducibility and user outcomes.

<!-- PAGE -->

## 06 | India-oriented competitors

## Screener
Screener documents listed-Indian-company financial data, historical screening, announcements, peer comparison and Excel exports. Screener AI adds company-document question answering, including annual reports and earnings calls. It is inaccurate to contrast ARIA's AI reports with a supposedly non-AI Screener. [S08, S09]

ARIA adds personal-finance and tutoring workflows around its own report logic. Some ARIA inputs come from Screener, so it is also an upstream dependency. ARIA's contribution is the transformation, integration and verification work around data, not ownership of those statements. [R03, R13, R14]

## Tickertape
Tickertape's site documents instrument discovery across stocks, funds, ETFs and indices, alongside screens, market information and learning content; the current site also includes U.S. stocks. India coverage alone cannot distinguish ARIA from it. [S10]

The narrower ARIA claim is an inspectable application combining profile calculations, explicit learner-state components and generated report artifacts. No evidence here shows better screening coverage, portfolio analytics or user experience than Tickertape.

## Trendlyne
Trendlyne documents screeners, DVM scores, analyst estimates, alerts and backtesting-related features. These overlap with multiple ARIA research and scenario concepts. Availability depends on the subscription. [S11]

ARIA's formula and test visibility is useful for a project review. It is not a substitute for proving a backtest free from leakage, survivorship bias or data-quality errors. No strategy-return comparison was conducted.

## Moneycontrol
Moneycontrol's subscription material describes market data, financial news, investment ideas and equity research. ARIA should not claim to replace its editorial or professional-research function. [S12]

ARIA is positioned as an interactive learning and calculation prototype. That is a different product emphasis, not a claim that Moneycontrol has no personal-finance coverage.

<!-- PAGE -->

## 07 | Specialist and institutional alternatives

## TradingView
TradingView documents charting, indicators, alerts, watchlists and Pine-based workflows. It is a relevant specialist for users focused on chart analysis and strategy tooling. [S13]

ARIA embeds Lightweight Charts and exposes selected market views. That library is not the full TradingView product. ARIA cannot claim equivalent charting, scripting, execution integrations or market entitlements merely because it uses a TradingView library. [R10]

## Yahoo Finance
Yahoo's official subscription description includes portfolio/watchlist tracking, news and premium research. Direct retrieval of that page failed in this review; this comparison uses only those narrow statements available in its official search result. [S14]

ARIA adds application-specific finance, tutoring and reporting, while also using Yahoo-derived price/fundamental inputs. A dependency cannot be honestly presented as data that ARIA uniquely owns or guarantees.

## Alpha Spread
Alpha Spread documents DCF and intrinsic-valuation tools, multiples analysis, fundamental analysis, earnings-call summaries and an AI assistant. Its valuation workflow is a close competitor to ARIA's equity-research component. [S15]

ARIA's potential value is inspectable formula/evidence handling and its connection to other application areas. Neither AI-assisted valuation nor DCF itself is new. Comparative valuation quality remains unmeasured.

## Bloomberg Terminal
Bloomberg describes professional research, analytics, financial workflows and AI-assisted research/news interfaces. Its reviewed material addresses financial professionals rather than a student prototype. [S16]

ARIA is not a demonstrated replacement for institutional data access, execution infrastructure or operational controls. The useful comparison is the scope difference: an educational, developer-controlled application versus professional financial infrastructure. Precise terminal prices, entitlements and latency guarantees were not verified here.

<!-- PAGE -->

## 08 | ARIA’s defensible differentiators

## 1. A particular integrated workflow
Personal planning, financial learning, market exploration and report review live in one application with shared state infrastructure. This can reduce context switching. Whether it actually saves time or improves decisions is a user-study question. [R04–R08]

## 2. Domain calculations as maintained code
Budget, goal, SIP/EMI and affordability results can be inspected in a finance engine. This enables regression tests on formulas and inputs. It distinguishes the project implementation from a bare chat prompt, but commercial assistants can also run code and maintain tools. [R04]

## 3. Explicit numeric provenance in equity reports
Report facts have types and metadata. Derived values reference input facts; assumptions remain separate from observations. The LLM is directed to cite evidence identifiers rather than create report numbers. This reduces a particular class of invented-number risk; wrong source data, mapping errors and misleading interpretations remain possible. [R03, R14]

## 4. Persistent workflows, not only conversational memory
Profiles, transactions, report versions, statement previews and retry receipts have storage behavior and ownership checks. Atomicity and restart tests are meaningful engineering work. Conversation memory alone would not provide those guarantees. [R05, R08, R09]

## 5. Finance-specific learner state
DKT and DQN components make learner modeling an explicit part of the implementation. This is a research hypothesis about better teaching, not validated educational effectiveness. Simulated training and real learner outcomes must be separated. [R06, R07, R16]

## 6. Developer control and reproducibility
The reviewer can inspect rules, rerun tests and modify a domain workflow without training a foundation model. This is useful academic engineering. Local deployment is not equivalent to fully local inference: external LLM and data requests still occur. [R01, R02, R15]

**Strength of claim:** These are defensible design and implementation differences. None establishes exclusive market novelty, certified advice, better investment returns or general superiority.

<!-- PAGE -->

## 09 | Is ARIA “just an LLM wrapper”?

## A useful distinction
A thin wrapper mainly forwards user text to a model and displays its response. ARIA contains additional domain engines, structured schemas, persistence, import transactions, retrieval, learner-state code, report calculations, source metadata and a React/FastAPI application. Those parts are testable independently of conversational fluency. [R03–R09, R13–R15]

## What belongs to the project contribution?
| Layer | Contribution to demonstrate | What not to claim |
| Foundation model | Provider integration, fallback and structured intent use. | Training or owning Groq/Gemini foundation-model intelligence. |
| Domain tools | Formulas, validation, assumptions and refusal of unsupported calculations. | A formula is novel merely because an LLM explains it. |
| Data and memory | Durable records, retrieval, owner scope and replay semantics. | Unlimited memory or perfect contextual understanding. |
| Reports | Evidence identifiers, deterministic numbers, versioning and export. | Guaranteed truth, certainty or profitable recommendations. |
| Learning | Concept retrieval, mastery state and action-selection components. | Proven human learning improvement without a study. |

## Honest novelty statement
The project demonstrates an independently implemented integration and engineering evaluation of established methods for a specific user group. It does not establish a new foundation-model algorithm. Its third-party notices acknowledge influences from FinRobot and ai-hedge-fund and the use of established models/libraries. [R10]

## Why the same LLM can still support a valid project
Using an existing model is compatible with meaningful application research. The evaluator should ask whether the system adds correct domain behavior, recoverable workflows, measurable utility and reproducibility. To isolate that contribution, compare ARIA with the same underlying model given the same inputs but without ARIA's tools and state. That is the appropriate ablation baseline; it has not yet been fully run.

<!-- PAGE -->

## 10 | Demonstration: household finance and learning

## Proposed demonstration A: a constrained savings goal
Use a synthetic profile: monthly take-home income INR 80,000; living expenses INR 35,000; EMI INR 12,000; goal contribution request INR 15,000. Ask what remains before other obligations. The arithmetic baseline is INR 33,000 before the requested contribution and INR 18,000 after it. This is illustrative arithmetic, not a personalized plan or a recorded live result.

### What to demonstrate in ARIA
1. Enter the profile and confirm the stored values after refresh.
2. Run the relevant calculation and identify which fields it used.
3. Explain that insurance, emergency reserves, irregular costs and other goals may change affordability.
4. Update one expense and confirm recomputation rather than reuse of the old result.
5. Ask what SIP and compounding mean, then answer a quiz and inspect learner-state behavior. [R04–R07]

### What makes the comparison fair?
Give each competitor the same synthetic data, the same task and permitted tools. Count wrong numbers, unsupported assumptions, clarification questions, user interactions and total completion time. Do not deprive a competitor of a calculator or file tool that its actual product provides.

## Proposed demonstration B: transaction import reliability
Import a synthetic statement, preview the rows, confirm once, retry the same confirmation and verify that transactions are not duplicated. Restart the test API and check the stored result. ARIA has recorded targeted coverage for transaction/import behavior; this proposed teaching demonstration should still be rerun on a test database. [R05]

## How to describe the difference
The useful contribution is a maintained workflow with explicit state and failure semantics. A competitor may analyze the same statement successfully. The experiment should test the whole workflow rather than only compare how polished the final paragraph sounds.

**Boundary:** Do not enter real bank records or classmates' financial data for a classroom demonstration. Synthetic inputs are sufficient for this engineering evaluation.

<!-- PAGE -->

## 11 | Demonstration: evidence-aware company research

## Proposed task
“Find the intended listed company from a partial name, prepare a report, show where the numbers came from, and explain which assumptions most affect valuation.” Use a fixed, dated input pack rather than allowing every product to retrieve a different quarter. A bank and a non-financial company should both be included. [R03, R11, R13, R14]

## Expected ARIA workflow to inspect
1. Select a canonical NSE/BSE ticker from company suggestions.
2. Inspect historical inputs and their source/date labels.
3. Trace a derived valuation fact to its input facts and assumptions.
4. Check the sensitivity to discount rate and terminal growth.
5. Inspect the verification gate, withheld values and missing-data warnings.
6. Save, reopen and export the versioned report.

The code includes different valuation treatment for businesses and banks. The analysis should check that an unsupported or inappropriate method is not forced onto the company simply to produce a number. [R13, R14]

## Three separate correctness questions
**Data correctness:** Was the correct reporting period, unit, entity and statement basis used? **Calculation correctness:** Given those inputs and assumptions, is the computed result reproducible? **Interpretation quality:** Does the explanation accurately describe what the result can and cannot imply?

Passing one does not prove the others. A mathematically correct DCF can still rely on incorrect historical data or an unreasonable terminal assumption. Multiple AI roles debating a conclusion are not independent expert validation.

## Competitor-aware interpretation
Perplexity, ChatGPT, Claude, Screener AI and Alpha Spread have overlapping research or modeling capabilities. A credible comparison measures the evidence and calculation chain, not whether a product uses the label “AI report.” [S01, S03, S05, S06, S09, S15]

**Boundary:** Market/news freshness, source rights, entity resolution and valuation uncertainty remain separate risks. Do not present a report stance as guaranteed return or regulated suitability advice.

<!-- PAGE -->

## 12 | What the recorded tests prove

## Engineering checkpoint, not a competitor benchmark
The repository's recorded audit at commit 49d071d reports the following. No full application regression suite was rerun merely to write this document; these are the previously recorded results. [R01, R02]

| Recorded evidence | Result | Correct interpretation |
| Python suite | 1,155 passed; zero failures, errors or skips. | The encoded assertions passed at that checkpoint. |
| Browser workflows | 26 private-mode + 4 account-mode passed. | Selected workflows worked in Chromium with isolated storage and synthetic providers. |
| Warnings | 104 Python warnings; 73 lint warnings. | Passing does not mean warning-free or defect-free. |
| Restart checks | Private and account restart checks passed. | Specific persisted data/session workflows survived tested restarts. |
| Dependency checks | No known advisories reported by the recorded scans. | A time-bound scan, not proof that the software is secure. |
| External connectivity | FRED timed out; other recorded checks passed. | One known provider failure remained. |
| Intent development set | 10/12 routes and 9/12 joint route/reference cases. | Small synthetic development fixture; not population-level accuracy. |
| Native memory fixture | Recall@5 = 1.0; MRR@5 = 0.9 across 10 queries. | Small retrieval fixture, not unlimited or human-equivalent memory. |

## What the evidence does not establish
- Better answers than Perplexity, ChatGPT or another competitor.
- Investment alpha, forecast accuracy or useful future returns.
- Learning gains for real students.
- Universal correctness across Indian tax and financial cases.
- Production scale, complete mobile/accessibility coverage, or real voice/video reliability.

Browser providers are synthetic; routing, API behavior and storage are real within the test setup. Treat this as meaningful engineering evidence with a defined scope. The overall recorded audit status remains **PARTIALLY VERIFIED**. Later UI edits are outside this full-suite checkpoint.

<!-- PAGE -->

## 13 | Risks, privacy, economics and deployment

## Data and financial limitations
ARIA depends on external data services and source parsing. Missing prices, stale feeds, reporting-basis mismatches and financial-unit errors can affect results. Configured valuation assumptions are not automatically live market estimates. Tax behavior is demonstrative and has documented scope/input limitations; this report does not certify tax-law correctness. [R02, R13, R14]

## Privacy and security
SQLite storage and local deployment give the operator control over application records. They do not make all processing on-device: cloud model calls and external data lookups remain part of the architecture. Credentials, logs, backups, prompts and provider retention must be considered separately. [R08, R09, R15]

Private mode trusts device-owner capabilities. Optional accounts add server-side sessions and ownership checks, but real Google consent, account recovery, verification, MFA and broader production controls are not all established by the recorded audit. Account-mode restrictions on unscoped paid-video/compute features are intentional limitations. Do not claim enterprise-grade compliance or stronger privacy than every commercial service. [R02, R09]

## Cost comparison without misleading prices
| ARIA cost driver | Fair comparison requirement |
| LLM usage | Measure tokens, tool calls, provider billing and fallback rate. |
| Hosting and inference | Include CPU/RAM, model downloads, disk, backups and operations. |
| Market data | Include data entitlements, provider terms and maintenance; public access is not a commercial redistribution license. |
| User effort | Measure configuration, imports, corrections and task completion time. |
| Commercial alternatives | Compare equivalent capabilities, regions and plans; subscription fees alone are insufficient. |

Free-tier development does not prove zero operating cost or sustainable unit economics. No matched cost-per-correct-task study or production load benchmark is available. Neither a cost advantage nor production readiness is claimed.

<!-- PAGE -->

## 14 | Evaluation plan suitable for a BTP

## Proposed test corpus — not completed results
Build a locked 120-task set: 30 personal-finance tasks, 30 company/valuation tasks, 20 fund/market tasks, 20 tutoring tasks and 20 dialogue/state-recovery tasks. Include misspellings, ambiguous companies, missing values, corrections, duplicate requests and unavailable providers. Review expected outputs independently before testing.

## Compare three baselines
**B0:** The same underlying LLM without ARIA's domain tools/state. **B1:** ARIA with the relevant component ablated. **B2:** Competitor products using their normal supported tools and matched access. Product features alone cannot substitute for this controlled experiment.

| Metric | How to measure it |
| Numeric correctness | Reference formulas and permitted rounding tolerances. |
| Source fidelity | Correct entity, reporting period, units and faithful attribution. |
| Task completion | Correct, persisted end state; reopening and retry behavior where applicable. |
| Refusal quality | Precision/recall on valid versus unsupported requests, including ambiguous cases. |
| Retrieval/intent | Recall@k and routing/reference accuracy on held-out examples. |
| User effort and speed | Interactions, correction burden and end-to-end p50/p95 latency. |
| Cost efficiency | Total measured cost per correctly completed task. |
| Learning benefit | Pre/post assessment, transfer questions and delayed retention. |

## Experimental controls
Freeze document packs and timestamps; separate live-news tasks from fixed-data tasks. Record model/version, plan, region, prompt, tool permissions and run date. Repeat stochastic tasks, use blinded raters, report disagreement and confidence intervals, and retain failures. Do not compare a best ARIA run against a single unassisted competitor run.

For tutoring, obtain appropriate consent and institutional approval before collecting student data. Use a power analysis for sample size and compare with both a static lesson and an LLM-only tutor. A simulated DQN reward is not an educational outcome.

<!-- PAGE -->

## 15 | Teacher questions and concise answers

### “What is the actual contribution?”
An implemented and inspectable combination of personal-finance logic, persistent workflows, learner-state components and evidence-aware Indian-company research. The contribution is system design and domain engineering; superiority remains to be evaluated.

### “Why use Groq or Gemini instead of training a model?”
The project can isolate its contribution above the foundation-model layer. Existing models supply language ability; domain code supplies calculations and state semantics. A same-model ablation tests whether that application layer adds value. [R15]

### “Why would someone use ARIA instead of Perplexity?”
For a specific India-focused learning/planning/report workflow and developer-level inspectability. Perplexity remains a strong research alternative. We have not proved broad research superiority. [S01, S02; R03–R08]

### “Does ARIA remove hallucinations?”
No. The report fact ledger constrains numerical narration, but source errors, unsupported interpretations and mapping mistakes remain possible. Verification reduces particular risks; it is not a truth guarantee. [R03, R14]

### “Is adaptive tutoring proven?”
The learner-model and teaching-policy components exist; real learning improvement is not established. The next step is a controlled, consented study. [R06, R07, R16]

### “Is this novel?”
The integration and implementation can be a valid BTP contribution. DCF, retrieval, knowledge tracing, reinforcement learning, multiple AI roles and report citations are established ideas. Prior influences and libraries must be acknowledged. [R10]

### “What should be improved first?”
First, verify source/input quality and owner isolation; next, expand held-out numeric, intent and refusal tests; then run the user and competitor evaluations. Broader voice, prediction and paid integrations should not outrank correctness and reproducibility.

## Recommended final claim
ARIA is a promising, partially verified finance-and-learning prototype with concrete engineering evidence. Its integrated workflow and inspectability justify evaluation; they do not establish that it outperforms commercial competitors.

<!-- PAGE -->

## Appendix 1 | References

## Sources and reproducibility
All online references accessed 17 October 2026. Repository links are pinned to the inspected commit. Vendor documentation establishes advertised capability, not comparative quality.

### [S01] Perplexity: Financial data in Research and Labs
[https://www.perplexity.ai/changelog/what-we-shipped-june-27th](https://www.perplexity.ai/changelog/what-we-shipped-june-27th)

### [S02] Perplexity: Price alerts, earnings hub and Morningstar research
[https://www.perplexity.ai/changelog/what-we-shipped-july-18th](https://www.perplexity.ai/changelog/what-we-shipped-july-18th)

### [S03] OpenAI: Deep research in ChatGPT
[https://help.openai.com/en/articles/10500283-deep-research-in-chatgpt](https://help.openai.com/en/articles/10500283-deep-research-in-chatgpt)

### [S04] OpenAI: Finances in ChatGPT
[https://help.openai.com/en/articles/20001222-finances-in-chatgpt](https://help.openai.com/en/articles/20001222-finances-in-chatgpt)

### [S05] ChatGPT Learn: Finance workflows
[https://learn.chatgpt.com/use-cases/collections/finance](https://learn.chatgpt.com/use-cases/collections/finance)

### [S06] Anthropic: Agents for financial services
[https://www.anthropic.com/news/finance-agents](https://www.anthropic.com/news/finance-agents)

### [S07] Google: Use Deep Research in Gemini Apps
[https://support.google.com/gemini/answer/15719111?hl=en](https://support.google.com/gemini/answer/15719111?hl=en)

### [S08] Screener: Features
[https://www.screener.in/features/](https://www.screener.in/features/)

<!-- PAGE -->

## Appendix 2 | References

## Sources and reproducibility
All online references accessed 17 October 2026. Repository links are pinned to the inspected commit. Vendor documentation establishes advertised capability, not comparative quality.

### [S09] Screener AI: Product description
[https://www.screener.in/ai/](https://www.screener.in/ai/)

### [S10] Tickertape: Research and investing platform
[https://www.tickertape.in/](https://www.tickertape.in/)

### [S11] Trendlyne: Subscription features
[https://trendlyne.com/subscription/plans-v2/](https://trendlyne.com/subscription/plans-v2/)

### [S12] Moneycontrol: Subscription products
[https://www.moneycontrol.com/subscription](https://www.moneycontrol.com/subscription)

### [S13] TradingView: Getting started with Supercharts
[https://www.tradingview.com/support/solutions/43000746464-getting-started-with-supercharts/](https://www.tradingview.com/support/solutions/43000746464-getting-started-with-supercharts/)

### [S14] Yahoo Finance: Subscription benefits
[https://finance.yahoo.com/subscriptions/](https://finance.yahoo.com/subscriptions/)

### [S15] Alpha Spread: Valuation tools
[https://www.alphaspread.com/](https://www.alphaspread.com/)

### [S16] Bloomberg: Financial news and Terminal solutions
[https://professional.bloomberg.com/products/bloomberg-terminal/news/introduction/](https://professional.bloomberg.com/products/bloomberg-terminal/news/introduction/)

<!-- PAGE -->

## Appendix 3 | References

## Sources and reproducibility
All online references accessed 17 October 2026. Repository links are pinned to the inspected commit. Vendor documentation establishes advertised capability, not comparative quality.

### [R01] ARIA: Recorded system audit results
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/SYSTEM_AUDIT_RESULTS.json](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/SYSTEM_AUDIT_RESULTS.json)

### [R02] ARIA: Audit findings and remaining risks
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/SYSTEM_AUDIT.md](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/SYSTEM_AUDIT.md)

### [R03] ARIA: Financial fact ledger
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/equity_research/intelligence/facts.py](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/equity_research/intelligence/facts.py)

### [R04] ARIA: Deterministic personal finance engine
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/finance/engine.py](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/finance/engine.py)

### [R05] ARIA: Statement import reliability
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/STATEMENT_IMPORT_RELIABILITY.md](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/STATEMENT_IMPORT_RELIABILITY.md)

### [R06] ARIA: Tutor pipeline
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/tutor/pipeline.py](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/tutor/pipeline.py)

### [R07] ARIA: DKT learner model and DQN teaching strategy
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/tutor/knowledge.py](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/tutor/knowledge.py)

### [R08] ARIA: Conversation memory implementation
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/CONTEXT_MEMORY_IMPLEMENTATION.md](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/CONTEXT_MEMORY_IMPLEMENTATION.md)

<!-- PAGE -->

## Appendix 4 | References

## Sources and reproducibility
All online references accessed 17 October 2026. Repository links are pinned to the inspected commit. Vendor documentation establishes advertised capability, not comparative quality.

### [R09] ARIA: Account authentication scope
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/ACCOUNT_AUTHENTICATION.md](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/ACCOUNT_AUTHENTICATION.md)

### [R10] ARIA: Attribution and third-party notices
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/THIRD_PARTY_NOTICES.md](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/THIRD_PARTY_NOTICES.md)

### [R11] ARIA: Search autocomplete implementation and checks
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/SEARCH_AUTOCOMPLETE.md](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/SEARCH_AUTOCOMPLETE.md)

### [R12] ARIA: News feed behavior
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/NEWS_FEED.md](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/reports/NEWS_FEED.md)

### [R13] ARIA: Valuation implementation
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/equity_research/intelligence/valuation.py](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/equity_research/intelligence/valuation.py)

### [R14] ARIA: Audit and verification gate
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/equity_research/intelligence/audit.py](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/equity_research/intelligence/audit.py)

### [R15] ARIA: Model client and provider fallback
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/ai/llm/groq_client.py](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/ai/llm/groq_client.py)

### [R16] ARIA: Tutor action policy
[https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/tutor/teaching.py](https://github.com/Karmanya30/ARIA_CLEAN/blob/49d071dcf7a87eabaf9ab029799f17be5262659c/modules/tutor/teaching.py)

### Scope notes
R07 points to the DKT implementation; R16 separately identifies the DQN teaching policy and its simulated-training qualification. R01 contains exact checkpoint counts and evaluation fixture results. R02 describes the outstanding audit risks. The README contains older statements about authentication and architecture, so detailed source and maintained audit reports were preferred when they conflicted.

### Report preparation
Prepared with AI assistance using official product sources and local repository evidence. This is an analytical synthesis, not an independent audit of commercial systems. No real account data, API credentials or investment positions are included. A teacher can reproduce the engineering evidence from the pinned repository and challenge the proposed comparisons using the experiment plan.
