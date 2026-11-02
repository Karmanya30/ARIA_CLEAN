"""Deterministic probes behind the user-value report (no model, no network). Output: results/probes.json
A intent coverage of the deterministic finance tools on natural phrasings
B Hinglish / typo normalisation and crisis detection (incl. Devanagari, false positives)
C memory across conversations, and what a deleted / archived / cleared chat leaves behind
D history panel back end: list, search, pin, archive, rename, export, paging, rating
E what a spoken or copied deterministic reply sounds like (speech_text)
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import harness as H
from shared.understand import normalize
from shared import human_state
from modules.finance.pipeline import finance_intent, finance_statement
from core.router import route_query
from shared import conversation_history as CH
from shared.user_store import current_owner

R = {}

# ---- A: phrasing coverage of the deterministic engine ------------------------------------------------------------------
A = [  # (phrasing, intended tool or None=any deterministic tool is acceptable, group)
 ("I want to save 1 crore in 15 years, how much do I need monthly?", "goal"),
 ("I want to build a corpus of 1 crore in 15 years", "goal"),
 ("how much to invest every month to reach 50 lakh in 10 years", "goal"),   # first person absent
 ("I need 50 lakh in 10 years for my daughter's education", "goal"),
 ("Can I afford a 25 lakh car loan?", "afford"),
 ("Can I buy a 25 lakh car?", "afford"),
 ("is a 1.2 lakh laptop on EMI okay for me", "afford"),
 ("Should I take a 50 lakh home loan?", "afford"),
 ("how much SIP can I do?", "sip_capacity"),
 ("I want to start a SIP of 5000", "afford_sip"),
 ("I earn 80000, how much should I invest?", "sip_capacity"),
 ("Is my emergency fund enough?", "health"),
 ("how many months of expenses do I have saved", "health"),
 ("how am I doing financially?", "health"),
 ("what is my savings rate", "health"),
 ("Which tax regime is better for me?", "tax"),
 ("Compare old and new tax regime for 12 lakh income", "tax"),
 ("how much tax will I pay this year", "tax"),
 ("when can I retire?", "retirement"),
 ("How long will my corpus of 80 lakh last if I spend 45000 a month?", "retirement"),
 ("What will be the EMI on a 50 lakh home loan at 8.5% for 20 years?", "emi"),
 ("EMI for 10 lakh at 12 percent for 5 years", "emi"),
 ("calculate emi 5 lakh 10% 3 years", "emi"),
 ("Where did I spend the most?", "spending"),
 ("how much did I spend on food last month", "spending"),
 ("where does my money go every month", "spending"),
 ("what are my biggest expenses", "spending"),
 ("what if I reduce my rent by 5000?", "what_if"),
 ("what if I cut my food spending by 2000", "what_if"),
 ("how much will 10000 a month in SIP become in 20 years", "sip_fv"),
]
rows = []
for q, tool in A:
    t, _ = normalize(q)
    hit = finance_intent(t)
    st = finance_statement(t)
    rows.append({"q": q, "intended": tool, "intent": hit[0] if hit else None, "statement": bool(st), "keyword_route": route_query(t)})
R["A"] = rows
R["A_summary"] = {"n": len(rows), "deterministic_tool_hit": sum(1 for r in rows if r["intent"]),
                  "intent_equals_intended": sum(1 for r in rows if r["intent"] == r["intended"])}

# ---- B: Hinglish / typo normalisation + crisis -------------------------------------------------------------------------
B = ["mujhe sip kitna karna chahiye 50000 salary mein", "nifti kaisa hai aaj", "wat is complund intrest", "reliace stock prise",
     "mera emi kitna hoga 20 lakh ka loan 9% pe 5 saal", "tax bachane ke liye kahan invest karu", "bhai paise nahi bachte, kya karu",
     "kya main 8 lakh ki car loan afford kar sakta hu", "sensex aaj kitna upar gaya", "mutual fund me paisa dalna safe hai kya",
     "म्यूचुअल फंड क्या है?", "मुझे 50000 की सैलरी में कितनी SIP करनी चाहिए", "ppf ka interest rate kitna hai", "emergency fund kitna hona chahiye",
     "hdfc bnk share price", "mutal fnd vs fd which is beter"]
R["B_normalize"] = [{"q": q, "normalized": normalize(q)[0], "changes": normalize(q)[1][:6]} for q in B]
CR = [("I feel like ending it all", True), ("I want to die", True), ("main marna chahta hu", True), ("mujhe jeena nahi hai", True),
      ("zindagi khatam kar dunga", True), ("मैं मरना चाहता हूँ", True), ("मुझे जीना नहीं है", True), ("i dont see a point in living anymore", True),
      ("kuch kha ke so jaunga hamesha ke liye", True), ("I lost everything in the market, I have nothing left to live for", True),
      ("this loss is killing me", False), ("my EMI is killing me", False), ("I will die if the market crashes again lol", False),
      ("how do I kill my credit card debt", False), ("I am dead broke", False)]
R["B_crisis"] = [{"q": q, "expected_crisis": e, "detected": human_state.is_crisis(q)} for q, e in CR]
R["B_crisis_summary"] = {"n_positive": sum(e for _, e in CR), "positive_detected": sum(1 for q, e in CR if e and human_state.is_crisis(q)),
                         "n_negative": sum(not e for _, e in CR), "false_positive": sum(1 for q, e in CR if not e and human_state.is_crisis(q))}

# ---- C: memory across conversations + deletion / archive / clear ---------------------------------------------------------
c = {}
H.seed_profile("uv_mem", monthly_income=100000, age=35, employment="salaried")
t1 = H.turn("uv_mem", "mem_A", "My daughter's school fee is 1.2 lakh a year and I am very risk averse")
t2 = H.turn("uv_mem", "mem_B", "How should I plan for my kid's school fees?")
ev = [x for x in t2["calls"] if "historical_evidence" in (x["prompt"] or "")]
c["cross_conversation_recall_in_prompt"] = bool(ev) and "school fee" in ev[0]["prompt"]
c["evidence_chars"] = len(ev[0]["prompt"]) if ev else 0
# delete conversation A, then ask again in a fresh conversation C
tok = current_owner.set("uv_mem")
CH.delete("mem_A")
listed = [i["id"] for i in CH.list_conversations()["items"]]
current_owner.reset(tok)
t3 = H.turn("uv_mem", "mem_C", "Remind me what you know about my daughter's school fee")
ev3 = [x for x in t3["calls"] if "historical_evidence" in (x["prompt"] or "")]
c["deleted_conv_hidden_from_list"] = "mem_A" not in listed
c["deleted_conv_still_in_model_context"] = bool(ev3) and "1.2 lakh" in ev3[0]["prompt"]
# archive: same check
tok = current_owner.set("uv_mem"); CH.archive("mem_B", True); current_owner.reset(tok)
# clear chat boundary
from core import session as core_session
tok = current_owner.set("uv_mem"); core_session.clear_session("mem_C"); current_owner.reset(tok)
t4 = H.turn("uv_mem", "mem_D", "What do you know about my daughter's school fee?")
ev4 = [x for x in t4["calls"] if "historical_evidence" in (x["prompt"] or "")]
c["after_clear_C_only_still_sees_A_B"] = bool(ev4) and "1.2 lakh" in ev4[0]["prompt"]
R["C_memory"] = c

# ---- D: history back end --------------------------------------------------------------------------------------------------
d = {}
H.seed_profile("uv_hist", monthly_income=60000, age=29, employment="salaried")
qs = [("h1", "Compare old and new tax regime for me"), ("h2", "Can I afford a 25 lakh car loan?"), ("h3", "What is a mutual fund?"),
      ("h4", "mujhe sip kitna karna chahiye 50000 salary mein"), ("h5", "म्यूचुअल फंड क्या है?")]
for sid, q in qs:
    H.turn("uv_hist", sid, q)
tok = current_owner.set("uv_hist")
lst = CH.list_conversations()
d["titles"] = [(i["id"], i["title"], i["messages"]) for i in lst["items"]]
CH.pin("h3", True); CH.rename("h2", "  Car   loan   check  "); CH.archive("h4", True)
d["after_pin_rename_archive"] = [(i["id"], i["title"], i["pinned"]) for i in CH.list_conversations()["items"]]
d["archived_list"] = [i["id"] for i in CH.list_conversations(archived=True)["items"]]
def srch(q): return [i["id"] for i in CH.list_conversations(q=q)["items"]]
d["search"] = {q: srch(q) for q in ["tax", "car", "mutual", "SIP", "grounding", "domain", "engine", "stub", "response", "numbers_checked", "Insight", "म्यूचुअल", "regime"]}
d["search_total_conversations_unarchived"] = len(CH.list_conversations()["items"])
name, media, body = CH.export("h1", "markdown")
d["export_md_h1"] = {"name": name, "body": body[:900]}
n2, m2, b2 = CH.export("h5", "markdown")
d["export_md_hindi_title"] = {"name": n2, "head": b2[:120]}
msgs = CH.messages("h1")
d["messages_h1"] = {"turns": len(msgs["turns"]), "keys": sorted(msgs["turns"][0].keys())}
try:
    CH.rate("h1", msgs["turns"][0]["message_id"], 1); d["rate_ok"] = True
    CH.rate("h1", msgs["turns"][0]["message_id"], 5)
except Exception as e:
    d["rate_invalid_raises"] = f"{type(e).__name__}: {e}"
d["rating_persisted"] = CH.messages("h1")["turns"][0]["rating"]
current_owner.reset(tok)
# another owner cannot see
tok = current_owner.set("uv_other")
try:
    CH.messages("h1"); d["other_owner_access"] = "ALLOWED"
except LookupError:
    d["other_owner_access"] = "404 (LookupError)"
d["other_owner_list_len"] = len(CH.list_conversations()["items"])
current_owner.reset(tok)
R["D_history"] = d

# ---- E: speech / copy of deterministic replies -------------------------------------------------------------------------------
from api.text_utils import speech_text
H.seed_profile("uv_sp", monthly_income=120000, age=31, employment="salaried", expenses=dict(rent=35000, food=15000, transport=5000, utilities=4000, entertainment=6000),
               assets=dict(cash=250000, mf=300000), tax_regime="new")
H.MODE = "down"
sp = []
for q in ["Can I afford a 60 lakh home loan?", "How much SIP can I start with my income?", "Compare old and new tax regime for me"]:
    r = H.turn("uv_sp", "sp_" + str(len(sp)), q, mode="Live Avatar (Free)")
    sp.append({"q": q, "written": r["response"], "spoken_field": r["spoken"], "speech_text(written)": speech_text(r["response"])})
R["E_speech"] = sp
R["env"] = {"stub_mode_E": H.MODE}
json.dump(R, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "results", "probes.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False, default=str)
print(json.dumps(R["A_summary"]), json.dumps(R["B_crisis_summary"]), json.dumps(R["C_memory"]))
