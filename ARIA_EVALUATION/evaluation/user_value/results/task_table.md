| id | persona | task | route | class | vs bare LLM | model-down reply | llm calls | note |
|---|---|---|---|---|---|---|---|---|
| P1-1 | P1 first-time investor | What is a mutual fund? | tutor | B | adds | degraded | 2 | concept lesson prompt (level 1/8, one analogy, rupee example); reply must parse into 3 labelled sections or the user sees 'couldn't reach my language model' |
| P1-2 | P1 first-time investor | How much should I invest in SIP every month if I earn 30000? | finance | A | unknown | template | 1 | stores income, asks for monthly spend (1 extra turn) instead of answering at once; bare LLM would give a rule of thumb immediately |
| P1-3 | P1 first-time investor | what is the difference between SIP and lumpsum | tutor | C | equal | degraded | 2 | generic tutor fallback, question + memory only |
| P1-4 | P1 first-time investor | Which stock will double next month? Guarantee it. | general | C | equal | degraded | 1 | general chat; system prompt says do not promise returns; refusal wording UNTESTED |
| P1-5 | P1 first-time investor | Quiz me on SIP | tutor | B | adds | degraded | 2 | quiz prompt; quiz widget/mastery tracking exist (UI UNTESTED) |
| P1-6 | P1 first-time investor | Should I buy Tata Motors shares or put money in FD? | investment | D | worse | degraded | 2 | equity module took 'FD' as the company (Company: FD); the shares-vs-FD comparison is never made |
| P1-7 | P1 first-time investor | I want to start investing but I am scared of losing money | support | F | worse | other | 1 | routed to the venting/self-doubt reply (2-3 sentences, one question); the beginner's real question gets no guidance |
| P1-8 | P1 first-time investor | How is the Nifty doing today? | market | E | unknown | degraded | 2 | market snapshot needs live data; degraded message only |
| P2-1 | P2 salaried saver, metro | Compare old and new tax regime for me | finance | A | adds | template | 2 | profile-based old vs new tax: new 88,140 vs old 2,19,960; both match my hand calculation on FY2025-26 slabs |
| P2-2 | P2 salaried saver, metro | Can I afford a 60 lakh home loan? | finance | A | adds | template | 2 | EMI/FOIR/emergency check from profile; assumes 20% down, 20y, 8.5% (loan shown as 48L for a '60 lakh home loan'); 'only -7.5 months' wording |
| P2-3 | P2 salaried saver, metro | How much SIP can I start with my income? | finance | A | adds | template | 2 | three SIP tiers from surplus 55k; engine numbers handed to the model with 'use only these numbers' |
| P2-4 | P2 salaried saver, metro | I want to save 1 crore in 15 years, how much do I need monthly? | finance | D | worse | degraded | 2 | question not in prompt: the generic 'risk profile + SIP amount' narration is asked for instead of the 1 crore / 15 years plan |
| P2-5 | P2 salaried saver, metro | What is my financial health score? | finance | A | adds | template | 2 | score 99/100 with insurance and goals unknown; coverage not stated in the sentence |
| P2-6 | P2 salaried saver, metro | What if I reduce my rent by 5000? | finance | A | adds | template | 2 | what-if: surplus 55k to 60k, 15y value; 'health score 100 to 100' shows the score saturates |
| P2-7 | P2 salaried saver, metro | Is my emergency fund enough? | finance | D | worse | degraded | 2 | same generic narration as P2-4 although the profile knows 6.2 months of cover; question not in prompt |
| P2-8 | P2 salaried saver, metro | Where did I spend the most? | general | D | worse | degraded | 2 | 10 seeded transactions ignored: routed to general chat with no transaction data |
| P2-9 | P2 salaried saver, metro | Which is better for me, ELSS or PPF? | general | C | equal | degraded | 2 | 'for me' but the general prompt carries no profile (tax regime, 80C, risk) - only memory |
| P3-1 | P3 student | I get 15000 a month as stipend, how much can I save? | finance | B | unknown | degraded | 2 | generic SIP narration; question 'how much can I save' not in prompt but SIP amount is roughly on topic |
| P3-2 | P3 student | Explain compound interest | tutor | B | adds | degraded | 2 | concept lesson prompt |
| P3-3 | P3 student | Can I afford a 1.2 lakh laptop on EMI? | finance | A | unknown | template | 1 | asks for monthly spend before judging the EMI (profile has income and age only) |
| P3-4 | P3 student | teach me about NPS | tutor | C | equal | degraded | 2 | tutor fallback; question + KB passages if matched (match not captured) |
| P3-5 | P3 student | What is an ETF? | tutor | B | adds | degraded | 2 | concept lesson prompt |
| P3-6 | P3 student | how do I make a budget for 15000 rupees | finance | B | adds | degraded | 2 | M1 pipeline includes an LP budget breakdown block; narration prompt omits the question |
| P3-7 | P3 student | Should I take an education loan? | finance | D | worse | degraded | 2 | education-loan question answered by the generic SIP narration for a 15k stipend |
| P3-8 | P3 student | Quiz me on mutual funds | tutor | B | adds | degraded | 2 | quiz prompt |
| P4-1 | P4 retiree | How long will my corpus of 80 lakh last if I spend 45000 a month? | finance | G | worse | degraded | 2 | decumulation (how long a corpus lasts) has no engine; generic SIP narration runs instead and does not say the feature is absent |
| P4-2 | P4 retiree | Is FD or SCSS better for me? | general | C | equal | degraded | 2 | age 63 / Conservative profile not in the prompt |
| P4-3 | P4 retiree | How is interest on FD taxed? | general | C | equal | degraded | 2 | memory only; whether the tax-rate wording is current is UNTESTED |
| P4-4 | P4 retiree | Should I sell my mutual funds now? The market looks shaky | finance | A | adds | template | 2 | decision-coaching template: asks goal and horizon, says it does not know actual returns; no model needed |
| P4-5 | P4 retiree | What is an annuity? | tutor | B | adds | degraded | 2 | concept lesson prompt |
| P4-6 | P4 retiree | Is my health insurance cover enough? | finance | D | worse | degraded | 3 | profile holds health cover 5L; generic SIP narration runs and the question is not in the prompt |
| P4-7 | P4 retiree | I am anxious about a market crash eating my savings | support | F | equal | other | 1 | support template; canned fallback text says 'being this hard on yourself' to someone who only voiced worry |
| P4-8 | P4 retiree | I feel like ending it all | care | F | adds | other | 0 | deterministic crisis reply with Tele-MANAS 14416 / 1-800-891-4416 and 112; no model, 0 calls |
| P5-1 | P5 small-business owner | My income varies a lot, how big should my emergency fund be? | finance | D | worse | degraded | 3 | variable income is in the profile (engine target would be 9 months) but the generic narration runs |
| P5-2 | P5 small-business owner | What will be the EMI on a 10 lakh business loan at 12% for 5 years? | finance | D | worse | template | 1 | 'EMI on a 10 lakh loan' parsed as the user's EMI = 10 lakh; budget-infeasible message plus 'Update EMI from 12k to 10L?'; nothing computes the EMI |
| P5-3 | P5 small-business owner | Can I afford a 10 lakh loan for my shop? | finance | A | unknown | template | 2 | asks about a 10 lakh loan, answers for an 8L loan (20% down assumed) at personal-loan terms |
| P5-4 | P5 small-business owner | Compare old and new tax regime for me | finance | A | unknown | template | 2 | salaried tax rules applied to a business-income profile: SUSPECTED |
| P5-5 | P5 small-business owner | How do I file GST returns for my shop? | general | D | worse | other | 1 | GST question entered the data-lookup branch (instrument search) and ended in a 'could not find reliable data' refusal with web search off |
| P5-6 | P5 small-business owner | How should I manage working capital? | general | C | equal | degraded | 2 | memory only |
| P5-7 | P5 small-business owner | Plan my monthly budget, I earn 90000 | finance | B | adds | degraded | 3 | M1 budget + risk + SIP blocks; narration prompt omits the question |
| P5-8 | P5 small-business owner | How should I separate personal and business money? | tutor | C | equal | degraded | 2 | tutor fallback, no business context |
| P6-1 | P6 experienced equity investor | Give me a research report on Infosys | equity_research | E | unknown | template | 1 | honest 'could not retrieve data', no numbers invented; report quality UNTESTED |
| P6-2 | P6 experienced equity investor | What is the PE ratio of ITC? | investment | D | worse | degraded | 2 | 'What is the PE ratio of ITC?' reached the investment module with Company: PE (first all-caps word) |
| P6-3 | P6 experienced equity investor | Compare revenue of Infosys and Wipro | equity_research | E | unknown | other | 1 | honest 'not available from Screener.in right now' |
| P6-4 | P6 experienced equity investor | Is HDFC Bank undervalued? | equity_research | E | unknown | template | 1 | honest failure |
| P6-5 | P6 experienced equity investor | What are the sentiment and red flags on Tata Motors? | investment | E | unknown | template | 2 | company not identified offline; ticker data BLOCKED |
| P6-6 | P6 experienced equity investor | What is my portfolio XIRR across my holdings? | finance | G | worse | degraded | 2 | no portfolio/holdings/XIRR feature; generic SIP narration runs and does not say so |
| P6-7 | P6 experienced equity investor | What is the tax on selling shares held for 2 years? | tutor | C | equal | degraded | 2 | memory only; correctness of current capital-gains rates UNTESTED |
| P6-8 | P6 experienced equity investor | What is the market cap of Ola Electric? | instrument | E | unknown | other | 1 | honest 'I don't have live data', lists what is unavailable |
| P6-9 | P6 experienced equity investor | How does XIRR differ from CAGR? | general | D | worse | other | 1 | concept question treated as a data lookup (refusal) with web search off |
| P7-1 | P7 Hinglish speaker | mujhe sip kitna karna chahiye 50000 salary mein | finance | B | unknown | degraded | 2 | normaliser makes 'me sip how much karna chahiye'; falls to the generic SIP narration, not the 3-tier engine the English phrasing gets |
| P7-2 | P7 Hinglish speaker | nifti kaisa hai aaj | general | D | worse | degraded | 2 | 'nifti' not corrected: routed to general chat, no market data |
| P7-3 | P7 Hinglish speaker | wat is complund intrest | tutor | B | adds | degraded | 2 | 'wat is complund intrest' corrected to 'what is compound interest' then tutor route |
| P7-4 | P7 Hinglish speaker | mera emi kitna hoga 20 lakh ka loan 9% pe 5 saal | finance | D | worse | template | 1 | same EMI mis-parse as P5-2: 'Update EMI from 0 to 20L?' |
| P7-5 | P7 Hinglish speaker | kya main 8 lakh ki car loan afford kar sakta hu | finance | D | worse | degraded | 2 | Hinglish 'afford' not recognised; generic SIP narration instead of an affordability verdict |
| P7-6 | P7 Hinglish speaker | bhai paise nahi bachte, kya karu | support | F | worse | other | 1 | support template (Hinglish fallback exists) for 'paise nahi bachte, kya karu', which asks for help saving |
| P7-7 | P7 Hinglish speaker | tax bachane ke liye kahan invest karu | finance | D | worse | degraded | 2 | tax-saving question answered by the generic SIP narration, question not in prompt |
| P7-8 | P7 Hinglish speaker | म्यूचुअल फंड क्या है? | general | C | equal | degraded | 2 | Devanagari is not normalised or routed; plain general chat |
