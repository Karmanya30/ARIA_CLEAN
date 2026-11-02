"""Run every persona task through modules.qa.pipeline.answer with the model stubbed. Output: results/tasks.json"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H
from tasks import PERSONAS

# synthetic transactions for P2 so "where did I spend most" has data
ROWS = [dict(date=f"2026-10-{d:02d}", category=c, amount=a, merchant=m, channel="UPI") for d, c, a, m in [
    (2, "Food", 1800, "Swiggy"), (5, "Food", 2200, "Zomato"), (7, "Transport", 900, "Uber"), (9, "Entertainment", 1500, "BookMyShow"),
    (12, "Food", 3100, "BigBasket"), (15, "Shopping", 8200, "Amazon"), (18, "Food", 1400, "Swiggy"), (21, "Transport", 1100, "Uber"),
    (25, "Utilities", 2400, "BESCOM"), (28, "Shopping", 5600, "Myntra")]]
out = []
for pname, p in PERSONAS.items():
    owner = "uv_" + pname.split()[0].lower()
    if p["seed"]:
        H.seed_profile(owner, **p["seed"])
    if pname.startswith("P2"):
        H.user_store.add_transactions(owner, ROWS)
    for i, (q, exp) in enumerate(p["tasks"], 1):
        r = H.turn(owner, f"{owner}_t{i}", q)
        r.pop("raw")
        r["persona"] = pname; r["id"] = f"{pname.split()[0]}-{i}"; r["exp"] = sorted(exp); r["route_ok"] = r["route"] in exp
        import re
        for c in r["calls"]:
            pr = c["prompt"] or ""
            core = re.sub(r"<historical_evidence>.*?</historical_evidence>", "", pr, flags=re.S)
            c["flags"] = {"memory_chars": len(pr) - len(core), "m1_narration_prompt": "COMPUTED DATA:" in core, "engine_json": "ENGINE RESULT (JSON)" in core,
                          "user_profile_block": "USER PROFILE" in core, "question_in_prompt": q.lower() in core.lower(), "is_output_guard": "domain classifier" in (c["system"] or "")}
            c["system_len"], c["prompt_len"] = len(c["system"] or ""), len(c["prompt"] or "")
            c["system"], c["prompt"] = (c["system"] or "")[:1500], (c["prompt"] or "")[:2500]
        out.append(r)
        print(r["id"], "|", r["route"], "| ok" if r["route_ok"] else "| MISS", "| llm", r["llm_calls"], "| net", r["net_attempts"], "| yf", r["yf_attempts"], "| err", r["error"], "|", q[:50], flush=True)
d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(d, exist_ok=True)
json.dump(out, open(os.path.join(d, "tasks_" + H.MODE + ".json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
