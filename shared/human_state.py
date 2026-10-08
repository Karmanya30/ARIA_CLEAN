"""Human State Engine: a cheap, deterministic read of how the user seems to feel and how ARIA should talk back.

    state = analyze(message, previous_trajectory)   # scores 0..1, intent, trajectory; no LLM, no network, ~0.2 ms
    plan = choose(state, prefs)                     # {strategy, format, length} or None for a normal turn
    block = style_block(state, plan, goals, prefs, episodes)

The block is a short tone guide appended to the *default* system prompt of every LLM call in the turn (ai/llm/groq_client.py
reads current_voice_block()). It changes wording only: routing, tools and engine numbers always get the original query.
Nothing here stores or logs message text: state carries category names and numbers, episodes carry a topic tag.

Ideas (not code) from: Psychological-State-Aware-Conversational-Ai (Apache-2.0: valence/arousal/stress state, trajectory,
hysteresis, episodic + semantic memory), aslp-lab/osum (Apache-2.0: understand, reason about empathy, then reply),
Empathetic-AI (no licence: safety gate first, no unsolicited task lists for a distressed user), COSMIC and conv-emotion
(MIT: conversation-level emotion with inertia, cause as a topic tag). See THIRD_PARTY_NOTICES.md.
"""
from __future__ import annotations

import math
import re
import time
from contextlib import contextmanager
from contextvars import ContextVar

_voice: ContextVar[tuple[str, dict] | None] = ContextVar("aria_voice", default=None)
_IDLE_RESET = 1800  # seconds without a message before the mood trajectory starts over

CARE_REPLY = (
    "I'm really sorry you are carrying this much right now, and I'm glad you said it out loud. You matter far more than any "
    "money worry. Please reach out to someone you trust today, a family member or a close friend, and try not to be alone "
    "with this. In India you can call Tele-MANAS on 14416 or 1-800-891-4416 (free, 24x7), and if you are in immediate danger "
    "call 112. I'm here and happy to keep talking.")


def _rx(*pairs: tuple[str, float]) -> list[tuple[re.Pattern, float]]:
    return [(re.compile(p), w) for p, w in pairs]


# ponytail: every lexicon below is a hand-weighted regex list. Known ceiling: recall on code-mixed and regional text
# (Marathi, Tamil, typos, new slang). Upgrade path: a small classifier behind a flag, scoring the same categories.
_AMT = r"(?:\d[\d,.]*\s*(?:%|k\b|l\b|lakhs?|cr\b|crores?|rs\b|rupees)|₹\s*\d|\d{1,3}(?:,\d{2,3})+|\d{4,})"
LEX = {
    "frustration": _rx((r"\bterrible\b", 1.2), (r"\bworst\b", 1.2), (r"\bfed up\b", 1.2), (r"\bpathetic\b", 1.2), (r"\bbakwas\b", 1.0),
                       (r"\bbekaar\b", 1.0), (r"\buseless\b", 1.0), (r"\bsick of\b", 1.0), (r"\bridiculous\b", 0.8), (r"\bhate\b", 0.8),
                       (r"\bfrustrat\w+", 1.0), (r"\bkharab\b", 0.8), (r"!!+", 0.6), (r"\bwaste of\b", 0.8)),
    "fear": _rx((r"\bwor(?:ried|ry|rying)\b", 1.0), (r"\bpanic\w*", 1.2), (r"\bcrash(?:ed|ing|es)?\b", 0.9), (r"\bscared\b", 1.2),
                (r"\bafraid\b", 1.1), (r"\btension\b", 1.0), (r"\bdar lag raha\b", 1.2), (r"\bghabra\w*", 1.2), (r"\bnervous\b", 1.0),
                (r"\banxi(?:ous|ety)\b", 1.1), (r"\bsleepless\b", 1.0), (r"\bwhat if\b", 0.5)),
    "sadness": _rx((r"\bhopeless\b", 1.2), (r"\bdepress\w+", 1.2), (r"\bheartbroken\b", 1.2), (r"\bgive up\b", 1.0), (r"\bfeel(?:ing)? low\b", 0.9),
                   (r"\budaas\b", 1.0), (r"\blost everything\b", 1.2), (r"\bno point\b", 1.0)),
    "self_doubt": _rx((r"\bi(?:'m| am) (?:so |such a |an? )?(?:stupid|dumb|idiot)\b", 1.5), (r"\bi always (?:mess|screw)", 1.5),
                      (r"\bmy fault\b", 1.0), (r"\b(?:should have|should've|shouldn't have)\b", 0.8), (r"\bgalti\b", 1.0),
                      (r"\bnever learn\b", 1.2), (r"\bbad with money\b", 1.0)),
    "joy": _rx((r"\brelieved\b", 1.2), (r"\bfinally\b", 0.7), (r"\bbadhiya\b", 1.0), (r"\bmast\b", 0.8), (r"\bhappy\b", 1.0),
               (r"\bthank god\b", 1.0), (r"\bexcited\b", 1.0), (r"\bgreat news\b", 1.0)),
    "financial": _rx((r"\b(?:loss|losses|lost|down|dropped|fell|negative)\b[^.?!]{0,25}?" + _AMT, 1.3),
                     (_AMT + r"[^.?!]{0,15}?\b(?:loss|losses|lost|down)\b", 1.3), (r"\bemi bounce\w*", 1.5),
                     (r"\b(?:can'?t|cannot|unable to) pay\b", 1.5), (r"\bsalary (?:delayed|late|not (?:come|credited))", 1.3),
                     (r"\b(?:terrible|bad|rough|poor|awful|kharab|negative)\b[^.?!]{0,25}\b(?:returns?|months?|years?|performance|chal rah\w*)", 1.5),
                     (r"\bin the red\b", 1.0), (r"\b(?:no money|paise nahi)\b", 1.0)),
    "urgency": _rx((r"\bright now\b", 1.0), (r"\btoday itself\b", 1.2), (r"\bjaldi\b", 1.0), (r"\b(?:asap|immediately|urgent\w*)\b", 1.0), (r"\babhi\b", 0.6)),
    "decision": _rx((r"\bshould i (?:sell|exit|redeem|stop|switch|withdraw|quit|book)", 1.0), (r"\b(?:sell|exit|redeem|bech|withdraw|nikal) (?:du|dun|doon|karu|kar du)\b", 1.0),
                    (r"\bstop (?:my |the )?sips?\b", 1.0), (r"\bsip band\b", 1.0), (r"\bswitch (?:to|funds)\b", 0.8)),
    "low_confidence": _rx((r"\bnot sure\b", 1.0), (r"\bconfused\b", 1.0), (r"\bpata nahi\b", 1.0), (r"\bsamajh nahi\b", 1.0), (r"\bno idea\b", 1.0),
                          (r"\b(?:don'?t|do not) (?:know|understand|get)\b", 0.8)),
    "risky": _rx((r"\ball in\b", 1.0), (r"\bput everything\b", 1.0), (r"\b(?:loan|borrow\w*)\b[^.?!]{0,15}\binvest", 1.0), (r"\bsure ?shot\b", 1.0),
                 (r"\bguaranteed (?:returns?|profit)", 1.0), (r"\bdouble my money\b", 1.0)),
}
# explicit self-harm only; finance idioms ("killing it", "this loss is killing me", "portfolio died") must not match
CRISIS = re.compile(r"\b(?:kill myself|end my life|suicid\w*|want to die|better off dead|hurt myself|jeena nahi|khudkushi|mar jaana|end it all|"
                    r"(?:don'?t|do not) want to (?:live|be alive|exist))\b")
NEGATIONS = {"not", "no", "never", "don't", "dont", "isn't", "aren't", "wasn't", "nahi", "nhi", "without", "hardly"}
INTENSIFIERS = {"very", "bahut", "bohot", "really", "extremely", "kaafi", "so", "too", "sooo", "soooo", "itna"}
HINGLISH = set(("hai hain nahi nahin kya yaar kitna kitni matlab theek thik bahut bohot mera mere meri mujhe tum aap hum karo karna kare kardu du dun "
                "bech lena dena abhi jaldi kuch koi bhai accha acha sahi galat paisa paise rupaye lekin magar aur toh bhi sab kaise kyun kyu kab kahan "
                "raha rahe rahi chahiye samajh seedha hoga wala wali ghabra kar").split())
_POS = re.compile(r"\b(?:great|wonderful|wah|wow|brilliant|fantastic|perfect|lovely|nice|thanks a lot|kya baat)\b")
_NEGMONEY = re.compile(r"\b(?:loss|losses|another|fee|fees|penalty|crash\w*|charged|down)\b")
_SARCASM = re.compile(r"yeah right|🙄|(?:^|\s)/s\b")
_TERSE = {"fine", "ok", "okay", "k", "whatever", "hmm", "hmmm", "theek", "thik", "sure", "nothing"}
_QUESTION = re.compile(r"\?|^(?:what|why|how|when|which|who|can|could|should|is|are|do|does|kya|kitna|kaise|kyun)\b")
_TOPICS = (("mutual fund", "funds"), ("sip", "sip"), ("stock", "stocks"), ("share", "stocks"), ("market", "market"), ("loan", "debt"),
           ("emi", "debt"), ("tax", "tax"), ("salary", "income"), ("crypto", "crypto"), ("insurance", "insurance"), ("goal", "goals"))
_EMOTIONS = ("frustration", "fear", "sadness", "self_doubt", "joy")


def _score(text: str, cat: str) -> float:
    """1 - exp(-sum of hit weights); a hit right after a negation (within 3 tokens) is dropped, after an intensifier it counts x1.3."""
    total = 0.0
    for rx, w in LEX[cat]:
        for m in rx.finditer(text):
            before = text[max(0, m.start() - 30):m.start()].split()[-3:]
            if cat not in ("decision", "risky") and NEGATIONS.intersection(before):
                continue
            total += w * (1.3 if INTENSIFIERS.intersection(before[-2:]) else 1.0)
    return 1 - math.exp(-total) if total else 0.0


def is_crisis(msg: str) -> bool:
    return bool(CRISIS.search(msg.lower().replace("’", "'")))


def analyze(msg: str, prev: dict | None = None, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    if prev and now - prev.get("ts", 0) > _IDLE_RESET:
        prev = None
    prev = prev or {}
    text = msg.lower().replace("’", "'")
    s = {c: _score(text, c) for c in LEX}
    caps = len(re.findall(r"\b[A-Z]{3,}\b", msg))
    if caps >= 2:
        s["frustration"] = max(s["frustration"], 0.5)
    words = re.findall(r"[a-z']+", text)
    hinglish = len(HINGLISH.intersection(words)) >= 2
    sarcasm = 0.6 if _SARCASM.search(text) or any(_POS.search(x) and _NEGMONEY.search(x) for x in re.split(r"[.!?]+", text)) else 0.0
    if sarcasm:
        s["joy"] = 0.0
    emotions = {c: s[c] for c in _EMOTIONS}
    neg = 1 - math.prod(1 - emotions[c] for c in _EMOTIONS if c != "joy")
    valence = max(-1.0, min(1.0, emotions["joy"] - max(neg, s["financial"])))
    if sarcasm:
        valence = -max(abs(valence), 0.5)
    stress = 1 - math.prod(1 - w * s[c] for c, w in (("fear", .8), ("frustration", .6), ("financial", .8), ("urgency", .6), ("self_doubt", .5), ("sadness", .5)))
    terse = len(words) <= 2 and bool(_TERSE.intersection(words)) and (prev.get("stress_ema", 0) > 0.4 or prev.get("last_valence", 0) < 0)
    if terse:
        stress, valence = prev.get("stress_ema", 0.0), prev.get("last_valence", 0.0)
    cues = {c: v for c, v in s.items() if v >= 0.2 and c not in ("decision", "risky")}
    top = sorted(cues.values(), reverse=True) + [0.0, 0.0]
    uncertainty = 1 - (top[0] - top[1]) + (0.2 if len(cues) < 2 or hinglish else 0.0) + (0.2 if sarcasm else 0.0)
    uncertainty = 0.7 if terse else max(0.0, min(1.0, uncertainty))
    question = bool(_QUESTION.search(text.strip()))
    crisis = is_crisis(msg)
    if crisis:
        intent = "crisis"
    elif s["decision"] >= 0.5:
        intent = "decision"
    elif max(neg, s["financial"], stress) >= 0.5 and not question or terse:
        intent = "venting"
    else:
        intent = "question" if question else "statement"
    ema = 0.5 * stress + 0.5 * prev.get("stress_ema", stress)  # a first message starts at its own stress
    hist = (prev.get("hist", []) + [ema])[-3:]
    delta = ema - (hist[-3] if len(hist) == 3 else hist[0] if len(hist) == 2 else 0.0)
    return {
        "emotions": emotions, "valence": valence, "arousal": min(1.0, max(s["frustration"], s["fear"], s["urgency"]) + 0.2 * (not terse and bool(caps))),
        "stress": stress, "confidence": 1 - s["low_confidence"], "sarcasm": sarcasm, "uncertainty": uncertainty, "intent": intent,
        "crisis": crisis, "hinglish": hinglish, "terse": terse, "risky": s["risky"] >= 0.5, "decision": s["decision"] >= 0.5,
        "topic": next((tag for key, tag in _TOPICS if key in text), "money"), "cues": sorted(cues),
        "trajectory": {"stress_ema": ema, "valence_ema": 0.5 * valence + 0.5 * prev.get("valence_ema", 0.0), "trend": "rising" if delta >= 0.15 else "falling" if delta <= -0.15 else "steady",
                       "ts": now, "hist": hist, "last_valence": valence, "prose": prev.get("prose", False),
                       "hing": (prev.get("hing", []) + [hinglish])[-5:]},
    }


def choose(state: dict, prefs: dict | None = None) -> dict | None:
    """Pick how to reply. Hysteresis: prose starts at stress >= .5 and only goes back to cards once the smoothed stress is < .35.
    Records the prose/cards choice in the trajectory. None = a normal turn (nothing changes)."""
    t, prefs = state["trajectory"], prefs or {}
    stress, em = state["stress"], state["emotions"]
    hold = t["prose"] and t["stress_ema"] >= 0.35
    if state["crisis"]:
        strategy, prose = "care", True
    elif state["decision"] and stress >= 0.5:
        strategy, prose = "challenge", True
    elif state["terse"]:
        strategy, prose = "ask", True
    elif em["self_doubt"] >= 0.5:
        strategy, prose = "reassure", True
    elif state["intent"] == "venting":
        strategy, prose = "listen", True
    elif stress >= 0.5:  # a stressed question (e.g. a market panic): answer calmly, in prose
        strategy, prose = "advise", True
    elif state["confidence"] <= 0.5 and state["intent"] in ("question", "decision"):
        strategy, prose = "explain", hold
    elif state["risky"]:
        strategy, prose = "challenge", hold
    elif hold:
        strategy, prose = "advise", True
    else:
        strategy, prose = None, False
    t["prose"] = prose
    if strategy is None:
        return None
    length = prefs.get("length") or ("short" if strategy in ("listen", "ask", "care") else "medium")
    return {"strategy": strategy, "format": "prose" if prose else "cards", "length": length}


_STRATEGY = {
    "challenge": "They are weighing a big money move. Acknowledge the rough stretch in a few words, slow the decision down, tie it to their own goal, and suggest checking their holdings before acting.",
    "listen": "They are venting. Acknowledge in a few words, reflect what they said in your own words, ask one gentle question. No task lists. Offer at most one small, concrete next step and ask before giving a plan.",
    "reassure": "They are being hard on themselves. Reassure first with one concrete, true positive, then explain the practical point simply. Offer at most one small, concrete next step and ask before giving a plan.",
    "ask": "Their reply was very short. Offer one gentle check-in question and keep it brief.",
    "explain": "They are unsure. One idea at a time, simple words, one everyday example.",
    "advise": "They are stressed. Answer their question calmly: lead with what is known, keep it factual, and say no action is needed today unless the data says otherwise.",
}
_ACK = {"challenge": "That sounds like a rough stretch.", "listen": "That sounds really frustrating.", "reassure": "Money slips happen to everyone.",
        "ask": "Take your time, no rush at all.", "advise": "Let's keep this simple."}


def style_block(state: dict, plan: dict | None, goals: list[dict] | None = None, prefs: dict | None = None, episodes: list[dict] | None = None) -> str:
    prefs, lines = prefs or {}, ["Tone guide for this reply (wording only):"]
    if plan:
        risky = plan["strategy"] == "challenge" and not state["decision"]
        lines.append("- " + ("Gently test their plan: name the main risk and ask what happens if it goes wrong." if risky else _STRATEGY.get(plan["strategy"], "")))
        lines.append("- Ignore any instruction to use Insight/Analysis/Recommendation/Risk labels this turn: write 2-4 short plain paragraphs, <=120 words, and do not write those label words at all."
                     if plan["format"] == "prose" else "- Keep the requested section format exactly; write each section like a person talking.")
    lines.append("- Lead with the answer in the first sentence. Plain words, short sentences, the user's own numbers. No 'As an AI', no 'I understand your concern', at most one specific caveat. "
                 "Use only numbers the user said or that are in their profile/engine result. Never make up their amounts, savings, income or history.")
    if state["hinglish"] or prefs.get("hinglish"):
        lines.append("- They write Hinglish (Hindi in Roman letters mixed with English): reply in that same register in Roman letters only (never Devanagari), mostly simple Hinglish with the finance terms in English ('koi tension nahi, abhi action ki zaroorat nahi hai'), never a caricature.")
    if state["uncertainty"] >= 0.6:
        lines.append("- Don't name their feeling; at most a light check-in.")
    if prefs.get("length") == "short":
        lines.append("- They like short answers: <=70 words.")
    elif prefs.get("length") == "detailed":
        lines.append("- They like detailed, step-by-step answers.")
    if prefs.get("directness") == "direct":
        lines.append("- They want it direct: no sugar-coating, no softeners.")
    if goals:
        lines.append("- Their goals: " + "; ".join(f"{g['name']} in {g['years']:g} years" for g in goals[:3] if g.get("name") and g.get("years")) + ".")
    if episodes and plan:
        lines.append(f"- Earlier they sounded {episodes[-1].get('feeling')} about {episodes[-1].get('topic_tag')} (do not mention unless they do).")
    lines.append("- Tone only: never change numbers or engine results. Never use feelings to push buy, sell, invest or urgency. When stressed, no action needed today "
                 "unless the result says otherwise. No diagnosing, no therapy language, never say 'I detect you are...'.")
    return "\n".join(lines)


_PREF_PHRASES = (("length", "short", ("keep it short", "tl;dr", "tldr", "short mein", "be brief")),
                 ("length", "detailed", ("explain in detail", "step by step", "in detail", "detail mein")),
                 ("directness", "direct", ("seedha bolo", "don't sugarcoat", "dont sugarcoat", "be blunt", "straight talk")))


def learn_prefs(msg: str, prefs: dict, hing_hist: list[bool]) -> dict:
    """Explicit phrases set a preference; Hinglish is set once 3 of the last 5 turns used it. Returns a new dict (same values = unchanged)."""
    text, out = msg.lower().replace("’", "'"), dict(prefs)
    for key, val, phrases in _PREF_PHRASES:
        if any(p in text for p in phrases):
            out[key] = val
    if sum(hing_hist) >= 3:
        out["hinglish"] = True
    return out


def add_episode(episodes: list[dict], state: dict, plan: dict, today: str) -> list[dict]:
    """Last 10 turns that needed care: date, topic tag, dominant feeling, strategy. No text, no amounts."""
    feeling = max(state["emotions"], key=state["emotions"].get) if max(state["emotions"].values()) >= 0.2 else "neutral"
    return (episodes + [{"date": today, "topic_tag": state["topic"], "feeling": feeling, "strategy": plan["strategy"]}])[-10:]


def soften(text: str, plan: dict | None = None) -> str:
    """Deterministic fallback voice: when the reply is prose-style, put a short acknowledgement after 'Insight:' so the card parser still works."""
    plan = plan or (_voice.get() or (None, None))[1]
    if not plan or plan["format"] != "prose" or not text.startswith("Insight:") or plan["strategy"] not in _ACK:
        return text
    return f"Insight: {_ACK[plan['strategy']]}" + text[len("Insight:"):]


_CHECK_INS = ("'Fine' can cover a lot after a rough stretch. Want to talk it through, or shall we just look at the numbers together?",
              "No pressure at all. If something is still sitting heavy I'm happy to listen, or we can leave it for now.",
              "That was a rough stretch. Do you want to go through it, or would a quiet moment be better?")
_CHECK_INS_HI = ("Theek hai, koi jaldi nahi. Kuch dil mein ho to bata sakte ho, ya phir hum numbers saath mein dekh lein?",
                 "Koi tension nahi, aaram se. Baat karni ho to main hoon, ya abhi rehne dete hain.")


def check_in(turn: int, hinglish: bool) -> str:
    """Deterministic, no-LLM reply to a bare "Fine." after a rough turn (a model tends to read it as good news)."""
    options = _CHECK_INS_HI if hinglish else _CHECK_INS
    return options[turn % len(options)]


def current_plan() -> dict | None:
    return (_voice.get() or (None, None))[1]


def current_voice_block() -> str | None:
    """The tone guide for the running turn (or None). Read by ai/llm/groq_client.py, same pattern as shared.news.current_news_block."""
    return (_voice.get() or (None, None))[0]


@contextmanager
def voice(block: str | None, plan: dict | None = None):
    token = _voice.set((block, plan) if block else None)
    try:
        yield
    finally:
        _voice.reset(token)


def quiet():
    """For LLM calls whose output is parsed by format (quiz, TAXAL): no tone block inside."""
    return voice(None)
