"""A fresh 'challenge' set written AFTER the fall-through fixes, to test whether those fixes generalise to similar questions
(not copies of the 12 failing ones). It is not part of benchmark_v1 and is never used for tuning. Includes negatives that must NOT be hijacked.

usage: python -X utf8 evaluation/intent_understanding/dataset_challenge.py   ->  benchmark_challenge.jsonl
"""
import json
from pathlib import Path

F, T, M, E, CI, D, G, S, CL = "finance", "tutor", "market", "equity_research", "company_intelligence", "data_lookup", "general", "smalltalk", "clarify"
ITEMS = [  # (query, primary, acceptable, category)
    # personal-money questions the old rules did not place
    ("is mahine kitna kharcha hua", F, (), "personal_money"), ("how much can I put away if I make 90k a month and pay 25k rent", F, (), "personal_money"),
    ("we earn 2 lakh and spend 1.5 lakh, can we save more", F, (), "personal_money"), ("how much did I spend on groceries last week", F, (), "personal_money"),
    ("our monthly expenses are 70000, how much should we keep as emergency fund", F, (T,), "personal_money"), ("kitna kharch ho raha hai mera rent pe", F, (), "personal_money"),
    # goal calculations
    ("how much should I save monthly to get 50 lakh in 10 years", F, (T,), "goal"), ("what monthly amount builds 2 crore in 25 years for me", F, (T,), "goal"),
    ("I want to accumulate 1 crore in 15 years, what monthly saving do I need", F, (), "goal"),
    # market and currency phrasings
    ("rupee vs dollar kaisa hai aaj", M, (D,), "market_phrasing"), ("how is the dollar doing against the rupee", M, (D,), "market_phrasing"),
    ("bazaar mein kya chal raha hai", M, (), "market_phrasing"), ("forex market today", M, (D,), "market_phrasing"), ("dollar rupee rate today", M, (D,), "market_phrasing"),
    ("how are the markets doing this week", M, (), "market_phrasing"),
    # finance concept definitions
    ("define liquidity", T, (G,), "concept"), ("what does CAGR mean", T, (), "concept"), ("meaning of expense ratio", T, (), "concept"),
    ("define rebalancing in investing", T, (), "concept"), ("what does alpha mean in investing", T, (), "concept"), ("what do you mean by diversification", T, (), "concept"),
    ("explain what a bond coupon is", T, (), "concept"),
    # decisions with nothing to decide about
    ("should I buy now", CL, (F,), "no_subject"), ("sell it all", CL, (F,), "no_subject"), ("exit everything", CL, (F,), "no_subject"), ("hold or sell?", CL, (F,), "no_subject"),
    # comparisons that name a company
    ("compare it with Infosys", E, (CL,), "comparison"), ("is HDFC Bank better than ICICI Bank", E, (), "comparison"), ("Infosys versus TCS", E, (), "comparison"),
    # performance of named instruments
    ("how did Ethereum do this month", D, (M,), "performance"), ("silver performance this year", D, (M,), "performance"), ("how did Nifty IT and gold do this week", M, (D,), "performance"),
    # negatives: must not be pulled into a financial route
    ("I spend hours reading novels", G, (), "negative"), ("hold the door please", G, (S,), "negative"), ("what does the word ubiquitous mean", G, (), "negative"),
    ("explain how a rainbow forms", G, (T,), "negative"), ("I earn my keep by writing code", G, (), "negative"), ("buy me a coffee joke", G, (), "negative"),
    ("sell your idea to the team, write an email", G, (), "negative"),
]
out = []
for i, (q, p, alts, cat) in enumerate(ITEMS, 1):
    out.append(dict(id=f"C{i:04d}", query=q, context=[], expected_primary=p, acceptable=list(alts), category=cat, source="challenge", secondary=[], entities=[],
                    expect_clarify=p == CL, unsupported=False, note="written after the fall-through fixes", scenario=None, turn=0, split="challenge"))
Path(__file__).with_name("benchmark_challenge.jsonl").write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n", encoding="utf-8")
print(len(out), "challenge items")
