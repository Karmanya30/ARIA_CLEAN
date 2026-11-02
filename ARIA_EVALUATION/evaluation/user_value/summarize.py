"""Evaluator's per-task judgement (a judgement, not a measurement) joined with the measured run. Output: results/summary.json, results/task_table.md
Outcome classes
 A  deterministic engine answer, personalised from the profile (no model needed for the numbers)
 B  model-dependent; the question AND the right grounding/profile reach the model (prose UNTESTED)
 C  model-dependent; only the bare question (+ conversation memory) reaches the model: equivalent to a bare LLM call
 D  defective path: question dropped, wrong route, wrong entity or mis-parsed fact
 E  needs live data; blocked offline, ARIA's honest degraded message observed
 F  support / safety template
 G  feature absent (and the reply does not say so)
vs bare LLM (structural judgement only): adds / equal / worse / unknown
"""
import json, os, collections
HERE = os.path.dirname(os.path.abspath(__file__))
J = {  # id: (class, vs_bare, note)
 "P1-1": ("B", "adds", "concept lesson prompt (level 1/8, one analogy, rupee example); reply must parse into 3 labelled sections or the user sees 'couldn't reach my language model'"),
 "P1-2": ("A", "unknown", "stores income, asks for monthly spend (1 extra turn) instead of answering at once; bare LLM would give a rule of thumb immediately"),
 "P1-3": ("C", "equal", "generic tutor fallback, question + memory only"),
 "P1-4": ("C", "equal", "general chat; system prompt says do not promise returns; refusal wording UNTESTED"),
 "P1-5": ("B", "adds", "quiz prompt; quiz widget/mastery tracking exist (UI UNTESTED)"),
 "P1-6": ("D", "worse", "equity module took 'FD' as the company (Company: FD); the shares-vs-FD comparison is never made"),
 "P1-7": ("F", "worse", "routed to the venting/self-doubt reply (2-3 sentences, one question); the beginner's real question gets no guidance"),
 "P1-8": ("E", "unknown", "market snapshot needs live data; degraded message only"),
 "P2-1": ("A", "adds", "profile-based old vs new tax: new 88,140 vs old 2,19,960; both match my hand calculation on FY2025-26 slabs"),
 "P2-2": ("A", "adds", "EMI/FOIR/emergency check from profile; assumes 20% down, 20y, 8.5% (loan shown as 48L for a '60 lakh home loan'); 'only -7.5 months' wording"),
 "P2-3": ("A", "adds", "three SIP tiers from surplus 55k; engine numbers handed to the model with 'use only these numbers'"),
 "P2-4": ("D", "worse", "question not in prompt: the generic 'risk profile + SIP amount' narration is asked for instead of the 1 crore / 15 years plan"),
 "P2-5": ("A", "adds", "score 99/100 with insurance and goals unknown; coverage not stated in the sentence"),
 "P2-6": ("A", "adds", "what-if: surplus 55k to 60k, 15y value; 'health score 100 to 100' shows the score saturates"),
 "P2-7": ("D", "worse", "same generic narration as P2-4 although the profile knows 6.2 months of cover; question not in prompt"),
 "P2-8": ("D", "worse", "10 seeded transactions ignored: routed to general chat with no transaction data"),
 "P2-9": ("C", "equal", "'for me' but the general prompt carries no profile (tax regime, 80C, risk) - only memory"),
 "P3-1": ("B", "unknown", "generic SIP narration; question 'how much can I save' not in prompt but SIP amount is roughly on topic"),
 "P3-2": ("B", "adds", "concept lesson prompt"),
 "P3-3": ("A", "unknown", "asks for monthly spend before judging the EMI (profile has income and age only)"),
 "P3-4": ("C", "equal", "tutor fallback; question + KB passages if matched (match not captured)"),
 "P3-5": ("B", "adds", "concept lesson prompt"),
 "P3-6": ("B", "adds", "M1 pipeline includes an LP budget breakdown block; narration prompt omits the question"),
 "P3-7": ("D", "worse", "education-loan question answered by the generic SIP narration for a 15k stipend"),
 "P3-8": ("B", "adds", "quiz prompt"),
 "P4-1": ("G", "worse", "decumulation (how long a corpus lasts) has no engine; generic SIP narration runs instead and does not say the feature is absent"),
 "P4-2": ("C", "equal", "age 63 / Conservative profile not in the prompt"),
 "P4-3": ("C", "equal", "memory only; whether the tax-rate wording is current is UNTESTED"),
 "P4-4": ("A", "adds", "decision-coaching template: asks goal and horizon, says it does not know actual returns; no model needed"),
 "P4-5": ("B", "adds", "concept lesson prompt"),
 "P4-6": ("D", "worse", "profile holds health cover 5L; generic SIP narration runs and the question is not in the prompt"),
 "P4-7": ("F", "equal", "support template; canned fallback text says 'being this hard on yourself' to someone who only voiced worry"),
 "P4-8": ("F", "adds", "deterministic crisis reply with Tele-MANAS 14416 / 1-800-891-4416 and 112; no model, 0 calls"),
 "P5-1": ("D", "worse", "variable income is in the profile (engine target would be 9 months) but the generic narration runs"),
 "P5-2": ("D", "worse", "'EMI on a 10 lakh loan' parsed as the user's EMI = 10 lakh; budget-infeasible message plus 'Update EMI from 12k to 10L?'; nothing computes the EMI"),
 "P5-3": ("A", "unknown", "asks about a 10 lakh loan, answers for an 8L loan (20% down assumed) at personal-loan terms"),
 "P5-4": ("A", "unknown", "salaried tax rules applied to a business-income profile: SUSPECTED"),
 "P5-5": ("D", "worse", "GST question entered the data-lookup branch (instrument search) and ended in a 'could not find reliable data' refusal with web search off"),
 "P5-6": ("C", "equal", "memory only"),
 "P5-7": ("B", "adds", "M1 budget + risk + SIP blocks; narration prompt omits the question"),
 "P5-8": ("C", "equal", "tutor fallback, no business context"),
 "P6-1": ("E", "unknown", "honest 'could not retrieve data', no numbers invented; report quality UNTESTED"),
 "P6-2": ("D", "worse", "'What is the PE ratio of ITC?' reached the investment module with Company: PE (first all-caps word)"),
 "P6-3": ("E", "unknown", "honest 'not available from Screener.in right now'"),
 "P6-4": ("E", "unknown", "honest failure"),
 "P6-5": ("E", "unknown", "company not identified offline; ticker data BLOCKED"),
 "P6-6": ("G", "worse", "no portfolio/holdings/XIRR feature; generic SIP narration runs and does not say so"),
 "P6-7": ("C", "equal", "memory only; correctness of current capital-gains rates UNTESTED"),
 "P6-8": ("E", "unknown", "honest 'I don't have live data', lists what is unavailable"),
 "P6-9": ("D", "worse", "concept question treated as a data lookup (refusal) with web search off"),
 "P7-1": ("B", "unknown", "normaliser makes 'me sip how much karna chahiye'; falls to the generic SIP narration, not the 3-tier engine the English phrasing gets"),
 "P7-2": ("D", "worse", "'nifti' not corrected: routed to general chat, no market data"),
 "P7-3": ("B", "adds", "'wat is complund intrest' corrected to 'what is compound interest' then tutor route"),
 "P7-4": ("D", "worse", "same EMI mis-parse as P5-2: 'Update EMI from 0 to 20L?'"),
 "P7-5": ("D", "worse", "Hinglish 'afford' not recognised; generic SIP narration instead of an affordability verdict"),
 "P7-6": ("F", "worse", "support template (Hinglish fallback exists) for 'paise nahi bachte, kya karu', which asks for help saving"),
 "P7-7": ("D", "worse", "tax-saving question answered by the generic SIP narration, question not in prompt"),
 "P7-8": ("C", "equal", "Devanagari is not normalised or routed; plain general chat"),
}
ok = {r["id"]: r for r in json.load(open(os.path.join(HERE, "results", "tasks_ok.json"), encoding="utf-8"))}
down = {r["id"]: r for r in json.load(open(os.path.join(HERE, "results", "tasks_down.json"), encoding="utf-8"))}
assert set(J) == set(ok), set(ok) ^ set(J)
rows, per = [], collections.defaultdict(collections.Counter)
for i, r in ok.items():
    c, v, note = J[i]
    per[r["persona"]][c] += 1
    dr = down[i]["response"]
    kind = "degraded" if down[i]["degraded"] else ("template" if dr.startswith(("Insight:", "I have your", "I wasn't able")) else "other")
    rows.append((i, r["persona"], r["q"], r["route"], c, v, kind, r["llm_calls"], r["yf_attempts"], note))
tot = collections.Counter(J[i][0] for i in J)
vs = collections.Counter(J[i][1] for i in J)
summary = {"n_tasks": len(J), "by_class": dict(tot), "vs_bare_llm": dict(vs), "per_persona": {k: dict(v) for k, v in per.items()},
           "model_down_degraded": sum(1 for i in down if down[i]["degraded"]), "model_down_template_answers": sum(1 for x in rows if x[6] == "template"),
           "llm_calls_mean": round(sum(r["llm_calls"] for r in ok.values()) / len(ok), 2),
           "tasks_with_output_guard_call": sum(1 for r in ok.values() if any(c["flags"]["is_output_guard"] for c in r["calls"])),
           "m1_question_dropped": [i for i, r in ok.items() if any(c["flags"]["m1_narration_prompt"] and not c["flags"]["question_in_prompt"] for c in r["calls"])],
           "finance_route_tasks": sum(1 for r in ok.values() if r["route"] == "finance")}
json.dump(summary, open(os.path.join(HERE, "results", "summary.json"), "w", encoding="utf-8"), indent=1)
with open(os.path.join(HERE, "results", "task_table.md"), "w", encoding="utf-8") as f:
    f.write("| id | persona | task | route | class | vs bare LLM | model-down reply | llm calls | note |\n|---|---|---|---|---|---|---|---|---|\n")
    for x in rows:
        f.write(f"| {x[0]} | {x[1]} | {x[2]} | {x[3]} | {x[4]} | {x[5]} | {x[6]} | {x[7]} | {x[9]} |\n")
print(json.dumps(summary, indent=1))
